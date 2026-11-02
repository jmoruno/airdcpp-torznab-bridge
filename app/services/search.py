import logging
import re
import time

from app.config import Settings
from app.models import SearchResult
from app.services.airdcpp import SEARCH_DEADLINE, SEARCH_YEAR, SEASON1_EPISODES, AirDCClient
from app.services.cache import AsyncTTLCache
from app.services.catalog import CatalogService
from app.services.database import Repository
from app.services.metadata import MediaMetadata, MetadataClient
from app.utils.text import clean_search_pattern, detect_languages, normalize_text, search_variants, title_roots, strip_diacritics

VIDEO_EXTENSIONS = (".mkv", ".avi", ".mp4", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg")
MIN_VIDEO_SIZE = 50 * 1024 * 1024
MIN_MOVIE_DIRECTORY_SIZE = 300 * 1024 * 1024
logger = logging.getLogger(__name__)
BRACKETS = re.compile(r"[\[{(][^\]})]*[\]})]")
LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese"}
# Lo que marca el final del titulo en un nombre de serie: S01, S01E07, 1x07, T01, "Temporada"...
SEASON_MARKER = re.compile(
    r"s\d{1,2}(?:e\d{1,4})?|e\d{1,4}|ep\d{1,4}|\d{1,2}x\d{1,4}|t\d{1,2}"
    r"|temporada|temporadas|temp|season|seasons|capitulo|capitulos|cap|episodio|episodios|episode|ep"
)
# Palabras que pueden ir entre el titulo y la temporada sin que sea otra serie
TITLE_NOISE = {
    "tv", "serie", "series", "anime", "completa", "completas", "complete", "pack", "integral",
    "castellano", "espanol", "spanish", "latino", "dual", "multi", "audio", "vose", "vos", "vo", "sub", "subs",
    "subtitulado", "subtitulos", "hd", "fullhd", "uhd", "4k", "us", "uk", "remastered", "remasterizado",
    "tvdb", "tmdb", "imdb", "hdtv", "web", "dl", "webdl", "webrip", "rip", "bluray", "bdrip", "dvdrip", "hdrip",
    "microhd", "x264", "x265", "h264", "h265", "hevc", "avc", "aac", "ac3", "dts", "proper", "repack",
}


class SearchService:
    def __init__(
        self,
        airdcpp: AirDCClient,
        metadata: MetadataClient,
        repository: Repository,
        cache: AsyncTTLCache[list[SearchResult]],
        settings: Settings,
        catalog: CatalogService | None = None,
    ):
        self.airdcpp = airdcpp
        self.metadata = metadata
        self.repository = repository
        self.cache = cache
        self.settings = settings
        self.catalog = catalog
        # Lo encontrado por cada busqueda en curso (o ya terminada) para poder ensenarlo antes de acabar
        self.progress: dict[str, tuple[dict, object]] = {}

    async def search(
        self,
        query: str | None,
        category: str | None,
        imdb_id: str | None,
        tmdb_id: str | None,
        tvdb_id: str | None,
        season: int | None,
        episode: int | None,
        absolute: int | None = None,
    ) -> list[SearchResult]:
        key = self._search_key(query, category, imdb_id, tmdb_id, tvdb_id, season, episode, absolute)

        async def perform() -> list[SearchResult]:
            nonlocal absolute
            # Margen para filtrar, guardar y generar el XML antes de RESPONSE_TIMEOUT
            deadline = time.monotonic() + self.settings.response_timeout - 15
            SEARCH_DEADLINE.set(deadline)
            media_type = "tv" if season is not None or absolute is not None or (category or "").startswith("5") else "movie"
            metadata = await self.metadata.details(query, imdb_id, tmdb_id, tvdb_id, media_type)
            titles = metadata.titles
            if not titles:
                return []
            # Una carpeta "Titulo - 01..74" vale como S01 si no pasa de lo que tiene la temporada 1
            seasons = {number: count for number, count in metadata.season_counts.items() if number >= 1}
            SEASON1_EPISODES.set(seasons.get(1) if len(seasons) > 1 else None)
            SEARCH_YEAR.set(metadata.year if media_type == "tv" else None)
            year_match = re.search(r"(?:\s|\()(\d{4})(?:\)|$)", query or "")
            variants = search_variants(titles, year_match.group(1) if year_match and media_type == "movie" else None)
            by_episode = season is not None and episode is not None
            # En un hub espanol los titulos en japones no encuentran nada y cada consulta cuesta ~15 s
            latin = [value for value in variants if all(c.isascii() or not c.isalpha() for c in strip_diacritics(value))]
            variants = latin or variants
            candidates: list[int] = []
            if absolute is not None and not by_episode:
                candidates.append(absolute)  # Sonarr (tipo Anime) ya pide el absoluto
            elif by_episode and metadata.anime:
                # Numeracion de TVmaze/TVDB (Nuvio, Sonarr); si no hay, la de TMDB
                counts = await self.metadata.episode_counts(imdb_id, tvdb_id) or metadata.season_counts
                if counts:
                    candidates.append(sum(count for number, count in counts.items() if 1 <= number < season) + episode)
                if absolute is not None:
                    candidates.append(absolute)  # numeracion de Cinemeta que calcula el addon (Stremio)
            absolute = tuple(dict.fromkeys(candidates)) or None
            per_title: list[str] = [f" {value:02d}" for value in absolute or ()]
            if by_episode:
                per_title += [f" S{season:02d}E{episode:02d}", f" {season}x{episode:02d}"]
            if absolute:
                logger.info("Anime: capitulo absoluto %s", "/".join(str(value) for value in absolute))
            if per_title:
                variants = [f"{variant}{suffix}" for variant in variants for suffix in per_title]
            max_variants = self.settings.search_max_variants * max(1, len(per_title))
            year = year_match.group(1) if year_match else None
            collected: dict[str, SearchResult] = {}
            self.progress[key] = (collected, metadata)
            while len(self.progress) > 300:
                self.progress.pop(next(iter(self.progress)))
            # Catálogo de la serie: si ya está armado, se contesta desde él sin ir a AirDC++. Si no trae nada en
            # el idioma de TMDB_LANGUAGE, se busca también como siempre y se suma.
            catalog_key = self._catalog_key(tvdb_id, tmdb_id, imdb_id)
            from_catalog = False
            catalog_ids: set[str] | None = None
            active_catalog = None
            known_folders: set[str] = set()
            if self.catalog and media_type == "tv" and (season is not None or absolute):
                catalog = self.catalog.find(catalog_key, titles)
                if catalog:
                    found_in_catalog = self.catalog.results(
                        catalog, season, episode, absolute or (), seasons.get(season) if season else None
                    )
                    found_in_catalog = self._filter_episode_or_absolute(
                        found_in_catalog, titles, year, season, episode, media_type, absolute
                    )
                    found_in_catalog = self._same_series(found_in_catalog, titles, tvdb_id, tmdb_id, metadata.year)
                    self._infer_languages(found_in_catalog, metadata)
                    for result in found_in_catalog:
                        collected[result.release_id] = result
                    catalog_ids = {self._identity(result) for result in collected.values()}
                    known_folders = catalog.folders_of()
                    wanted = LANGUAGE_NAMES.get(metadata.localized_language)
                    # Solo contesta solo cuando está verificado: hasta entonces se busca también como siempre y se
                    # compara (AirDC++ no devuelve lo mismo cada vez, así que no basta con cómo se armó)
                    from_catalog = self.catalog.trusted(catalog)
                    active_catalog = catalog
                    logger.info(
                        "Catálogo de %r: %d resultados (%d en el idioma)%s",
                        catalog.titles[0],
                        len(found_in_catalog),
                        sum(bool(wanted) and wanted in result.languages for result in found_in_catalog),
                        "" if from_catalog else f"; sin verificar ({catalog.verified}), se busca también",
                    )
                    if from_catalog:
                        variants = []
            for position, variant in enumerate(variants[:max_variants], start=1):
                # Cada variante cuesta la cola de AirDC++ mas SEARCH_TIMEOUT
                if position > 1 and time.monotonic() + self.settings.search_timeout + 15 > deadline:
                    total = min(len(variants), max_variants)
                    logger.warning("Sin tiempo para mas variantes: %d de %d", position - 1, total)
                    break
                raw = await self.airdcpp.search(
                    [variant], season if episode is None and absolute is None else None, VIDEO_EXTENSIONS
                )
                filtered = self._filter_episode_or_absolute(raw, titles, year, season, episode, media_type, absolute)
                series_year = metadata.year if media_type == "tv" else None
                filtered = self._same_series(filtered, titles, tvdb_id, tmdb_id, series_year)
                duplicates = 0
                for result in filtered:
                    if result.release_id in collected:
                        duplicates += 1
                    else:
                        # Guardado ya para poder reproducirlo/descargarlo antes de que acabe la busqueda
                        await self.repository.save_release(result)
                        if result.tth:
                            await self.repository.save_hash(result.tth, result.release_id)
                    collected[result.release_id] = result
                # En capitulos solo cuentan los que empiezan por el titulo: "Ultimate Spiderman" no vale para "Spiderman"
                if (season is not None and episode is not None) or absolute is not None:
                    found = sum(1 for value in collected.values() if self._title_first(value.name, titles))
                else:
                    found = len(collected)
                enough = found >= self.settings.search_min_accepted_results
                logger.info(
                    "Variante %d/%d query=%r raw=%d validos=%d duplicados=%d acumulados=%d decision=%s",
                    position,
                    min(len(variants), max_variants),
                    variant,
                    len(raw),
                    len(filtered),
                    duplicates,
                    len(collected),
                    "detener" if enough else "continuar",
                )
                if enough:
                    break
            filtered_results = self._filter_episode_or_absolute(
                list(collected.values()), titles, year, season, episode, media_type, absolute
            )
            results = self._deduplicate_file_directories(filtered_results)
            if active_catalog is not None and catalog_ids is not None:
                # El catálogo sabe en qué carpeta está cada fichero: si conoce uno que la búsqueda normal ha dado por
                # bueno y no es este capítulo (otra serie con el mismo título, otra numeración), se quita. Lo que
                # el catálogo no conoce se queda, para no perder nada.
                kept = [
                    result
                    for result in results
                    if self._identity(result) in catalog_ids or not active_catalog.knows(result.tth)
                ]
                if len(kept) != len(results):
                    dropped = len(results) - len(kept)
                    logger.info("Catálogo: %d resultados de la búsqueda normal no son este capítulo", dropped)
                results = kept
            self._infer_languages(results, metadata)
            logger.info(
                "Deduplicacion semantica: entrada=%d salida=%d eliminados=%d",
                len(filtered_results),
                len(results),
                len(filtered_results) - len(results),
            )
            for result in results:
                await self.repository.save_release(result)
                if result.tth:
                    await self.repository.save_hash(result.tth, result.release_id)
            if catalog_ids is not None and active_catalog is not None and not from_catalog:
                # Verificación: ¿ha traído la búsqueda normal algo que no tuviera el catálogo?
                extra = [
                    result
                    for result in results
                    if self._identity(result) not in catalog_ids
                    and not active_catalog.knows(result.tth)
                    and f"{result.source_cid}:{normalize_text(result.source_path or '')}" not in known_folders
                ]
                self.catalog.verify(active_catalog, len(extra))
                logger.info(
                    "Búsqueda además del catálogo: %d nuevos (%d en castellano); verificado %d/%d%s",
                    len(extra),
                    sum("Spanish" in result.languages for result in extra),
                    active_catalog.verified,
                    self.settings.catalog_verify_requests,
                    "".join(f" | {result.source_path or result.name}" for result in extra[:3]),
                )
            if self.catalog and media_type == "tv" and not from_catalog:
                # Lo pedido ya está contestado; el resto de la serie se prepara detrás
                self.catalog.ensure(catalog_key, titles, metadata.year)
            return results

        return await self.cache.get_or_create(key, perform)

    @staticmethod
    def _identity(result: SearchResult) -> str:
        """Mismo fichero o carpeta aunque venga del catálogo o de la búsqueda normal con otro nombre."""
        if result.tth:
            return result.tth
        return f"{result.source_cid}:{normalize_text(result.source_path or result.name)}"

    @staticmethod
    def _catalog_key(tvdb_id: str | None, tmdb_id: str | None, imdb_id: str | None) -> str | None:
        for kind, value in (("tvdb", tvdb_id), ("tmdb", tmdb_id), ("imdb", imdb_id)):
            if value:
                return f"{kind}:{value}"
        return None

    @staticmethod
    def _search_key(query, category, imdb_id, tmdb_id, tvdb_id, season, episode, absolute) -> str:
        category_family = (category or "").split(",", maxsplit=1)[0][:1]
        if query:
            # Radarr puede repetir la misma búsqueda variando los IDs externos.
            # Compartir la entrada evita relanzar una consulta idéntica al hub.
            return "|".join(str(value or "") for value in (normalize_text(query), category_family, season, episode, absolute))
        return "|".join(str(value or "") for value in (category_family, imdb_id, tmdb_id, tvdb_id, season, episode, absolute))

    def peek(self, query, category, imdb_id, tmdb_id, tvdb_id, season, episode, absolute=None) -> list[SearchResult]:
        """Lo encontrado hasta ahora por la misma busqueda (vacio si aun no ha empezado)."""
        found, metadata = self.progress.get(
            self._search_key(query, category, imdb_id, tmdb_id, tvdb_id, season, episode, absolute), ({}, None)
        )
        results = list(found.values())
        if metadata is not None:
            self._infer_languages(results, metadata)
        return results

    @classmethod
    def _filter_episode_or_absolute(cls, results, titles, year, season, episode, media_type, absolute):
        by_episode = season is not None and episode is not None
        if absolute is None:
            return cls._filter_and_rank(results, titles, year, season, episode, media_type)
        accepted = cls._filter_and_rank(results, titles, year, season, episode, media_type) if by_episode else []
        seen = {value.release_id for value in accepted}
        for value in cls._filter_and_rank(results, titles, year, None, None, media_type, absolute):
            if value.release_id not in seen and cls._absolute_match(value.name, titles, absolute):
                seen.add(value.release_id)
                accepted.append(value)
        return accepted

    @classmethod
    def _absolute_match(cls, name: str, titles: list[str], absolute) -> bool:
        values = (absolute,) if isinstance(absolute, int) else tuple(absolute or ())
        return any(cls._absolute_match_one(name, titles, value) for value in values)

    @staticmethod
    def _absolute_match_one(name: str, titles: list[str], absolute: int) -> bool:
        """El primer numero tras el titulo es el capitulo absoluto: 'GT 61', 'GT_61', 'GT E61', '(0061)', '01x61', 'S01E61'."""
        words = normalize_text(name.replace("_", " ")).split()
        aliases = [normalize_text(clean_search_pattern(title)) for title in titles] + [
            normalize_text(root) for root in title_roots(titles)
        ]
        aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in aliases]
        skip = {"ep", "e", "episodio", "episode", "capitulo", "cap", "chapter", "no", "n"}
        patterns = (rf"0*{absolute}", rf"e0*{absolute}", rf"ep0*{absolute}", rf"s\d{{1,2}}e0*{absolute}", rf"\d{{1,2}}x0*{absolute}")
        for alias in dict.fromkeys(alias for alias in aliases if alias):
            phrase = alias.split()
            for index in range(min(3, len(words))):
                if words[index : index + len(phrase)] != phrase:
                    continue
                position = index + len(phrase)
                skipped = 0
                while position < len(words) and skipped < 3 and (
                    words[position] in skip or re.fullmatch(r"(?:19|20)\d{2}", words[position])
                ):
                    position += 1
                    skipped += 1
                if position < len(words) and any(re.fullmatch(p, words[position]) for p in patterns):
                    return True
        return False

    @staticmethod
    def _title_first(name: str, titles: list[str]) -> bool:
        words = normalize_text(name.replace("_", " ")).split()
        aliases = [normalize_text(clean_search_pattern(title)) for title in titles] + [
            normalize_text(root) for root in title_roots(titles)
        ]
        aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in aliases]
        return any(alias and words[: len(alias.split())] == alias.split() for alias in aliases)

    @staticmethod
    def _same_series(
        results: list[SearchResult],
        titles: list[str],
        tvdb_id: str | None,
        tmdb_id: str | None,
        series_year: str | None,
    ) -> list[SearchResult]:
        """Fuera las de otra serie con el mismo titulo: "{tvdb-389492}" o "Monster (2022)" buscando la de 2004."""
        aliases = [normalize_text(clean_search_pattern(title)) for title in titles]
        aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in aliases]
        aliases = [alias.split() for alias in dict.fromkeys(aliases) if alias]
        kept: list[SearchResult] = []
        for result in results:
            words = normalize_text(result.name.replace("_", " ")).split()
            spaced = " ".join(words)
            ids = {"tvdb": tvdb_id, "tmdb": tmdb_id}
            if any(
                expected and (match := re.search(rf"\b{kind} ?(\d+)\b", spaced)) and match.group(1) != str(expected)
                for kind, expected in ids.items()
            ):
                logger.info("Descartado por ser otra serie (id): %s", result.name)
                continue
            if series_year:
                ends = [
                    index + len(alias)
                    for alias in aliases
                    for index in range(min(3, len(words)))
                    if words[index : index + len(alias)] == alias
                ]
                following = words[max(ends)] if ends and max(ends) < len(words) else ""
                if re.fullmatch(r"(?:19|20)\d{2}", following) and abs(int(following) - int(series_year)) > 1:
                    logger.info("Descartado por ser otra serie (ano %s): %s", following, result.name)
                    continue
            kept.append(result)
        return kept

    @staticmethod
    def _other_series(words: list[str], full_aliases: list[str], root_aliases: list[str], titles: list[str]) -> bool:
        """'Monster The Ed Gein Story S01' no es 'Monster S01': palabras de mas entre el titulo completo y la temporada.

        Solo cuenta cuando el nombre lleva el titulo completo; con la raiz ("Frieren" de "Frieren: Beyond
        Journey's End") lo que sigue suele ser el subtitulo en otro idioma. Sin marca de temporada no decide.
        """
        best: tuple[int, bool] | None = None
        for alias in full_aliases + root_aliases:
            phrase = alias.split()
            for index in range(min(3, len(words) - len(phrase) + 1)):
                if words[index : index + len(phrase)] == phrase:
                    end = index + len(phrase)
                    if best is None or end > best[0] or (end == best[0] and alias in full_aliases):
                        best = (end, alias in full_aliases)
        if best is None or not best[1]:
            return False
        # Lo que va entre parentesis en el titulo, "(US)" en "The Office (US)", tambien vale
        bracketed = [part for title in titles for part in re.findall(r"\(([^)]*)\)", title)]
        allowed = TITLE_NOISE | {word for part in bracketed for word in normalize_text(part).split()}
        extra = 0
        for word in words[best[0] :]:
            if SEASON_MARKER.fullmatch(word):
                return extra > 0
            if word in allowed or word.isdigit() or re.fullmatch(r"\d{3,4}p", word):
                continue
            extra += 1
        return False

    @staticmethod
    def _filter_and_rank(
        results: list[SearchResult],
        titles: list[str],
        year: str | None,
        season: int | None,
        episode: int | None,
        media_type: str = "movie",
        absolute: int | None = None,
    ) -> list[SearchResult]:
        full_aliases = [normalize_text(clean_search_pattern(title)) for title in titles]
        full_aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in full_aliases]
        full_aliases = list(dict.fromkeys(alias for alias in full_aliases if alias))
        root_aliases = [normalize_text(root) for root in title_roots(titles)]
        root_aliases = [alias for alias in root_aliases if alias not in full_aliases]
        accepted: list[tuple[int, SearchResult]] = []
        rejected = {"size": 0, "type": 0, "title": 0, "year": 0, "sequel": 0, "other_series": 0, "episode": 0}
        other_series: list[str] = []

        for result in results:
            if result.item_type not in {"file", "directory", "bundle"}:
                rejected["type"] += 1
                continue
            if result.size < MIN_VIDEO_SIZE:
                rejected["size"] += 1
                continue
            if (
                media_type == "movie"
                and result.item_type in {"directory", "bundle"}
                and result.size < MIN_MOVIE_DIRECTORY_SIZE
            ):
                rejected["size"] += 1
                continue
            words = normalize_text(result.name.replace("_", " ")).split()
            matches: list[tuple[int, bool]] = []
            for alias in full_aliases + root_aliases:
                phrase = alias.split()
                matches.extend(
                    (index, alias in full_aliases)
                    for index in range(len(words) - len(phrase) + 1)
                    if words[index : index + len(phrase)] == phrase
                )
            # Los títulos deben aparecer como palabras completas y cerca del principio.
            if not matches or min(position for position, _ in matches) > 2:
                rejected["title"] += 1
                continue
            if year and year not in words:
                rejected["year"] += 1
                continue
            incompatible_number = False
            for alias in full_aliases + root_aliases:
                phrase = alias.split()
                for index in range(len(words) - len(phrase)):
                    if words[index : index + len(phrase)] != phrase:
                        continue
                    following = words[index + len(phrase)]
                    if (
                        following.isdigit()
                        and following != year
                        and int(following) not in ((absolute,) if isinstance(absolute, int) else tuple(absolute or ()))
                        and 1 <= int(following) <= (99 if media_type == "tv" else 20)
                    ):
                        incompatible_number = True
            if incompatible_number:
                rejected["sequel"] += 1
                continue
            # Lo que va entre corchetes son etiquetas ("[Cast+Jap+Subs]"), no parte del título
            unbracketed = normalize_text(BRACKETS.sub(" ", result.name).replace("_", " ")).split()
            if media_type == "tv" and SearchService._other_series(unbracketed, full_aliases, root_aliases, titles):
                rejected["other_series"] += 1
                other_series.append(result.name)
                continue
            if season is not None and episode is not None:
                spaced = " ".join(words)
                episode_patterns = (
                    rf"(?<![a-z0-9])s0*{season} ?e0*{episode}(?![0-9])",
                    rf"(?<![0-9])0*{season} ?x ?0*{episode}(?![0-9])",
                )
                if not any(re.search(pattern, spaced) for pattern in episode_patterns):
                    rejected["episode"] += 1
                    continue
            best_position = min(position for position, _ in matches)
            score = 100 - best_position * 10
            score += 25 if any(full for _, full in matches) else 0
            score += 10 if year and year in words else 0
            score += 4 if result.tth else 0
            score += 2 if result.item_type == "file" else 0
            accepted.append((score, result))

        accepted.sort(key=lambda pair: (-pair[0], normalize_text(pair[1].name), -pair[1].size))
        logger.info("Filtro de relevancia: raw=%d aceptados=%d descartados=%s", len(results), len(accepted), rejected)
        if other_series:
            # Regla nueva: se registran para poder revisar que no se cuela una serie buena
            logger.info("Descartados por ser otra serie: %s", " | ".join(sorted(set(other_series))[:10]))
        return [result for _, result in accepted]

    @staticmethod
    def _deduplicate_file_directories(results: list[SearchResult]) -> list[SearchResult]:
        def identity_words(name: str) -> list[str]:
            words = normalize_text(name).split()
            ignored = {"mkv", "mp4", "avi", "m4v", "mov", "wmv", "mpg", "mpeg"}
            cleaned: list[str] = []
            skip_identifier = False
            for word in words:
                if word in {"tmdb", "imdb", "tvdb"}:
                    skip_identifier = True
                    continue
                if skip_identifier and word.isdigit():
                    skip_identifier = False
                    continue
                skip_identifier = False
                if word not in ignored:
                    cleaned.append(word)
            return cleaned

        kept: list[SearchResult] = []
        for candidate in results:
            duplicate_index = None
            candidate_words = identity_words(candidate.name)
            for index, existing in enumerate(kept):
                candidate_is_file = candidate.item_type == "file"
                existing_is_file = existing.item_type == "file"
                if candidate_is_file == existing_is_file:
                    continue
                tolerance = max(1024 * 1024, int(max(candidate.size, existing.size) * 0.002))
                if abs(candidate.size - existing.size) > tolerance:
                    continue
                existing_words = identity_words(existing.name)
                shorter, longer = sorted((candidate_words, existing_words), key=len)
                if longer[: len(shorter)] == shorter:
                    duplicate_index = index
                    break
            if duplicate_index is None:
                kept.append(candidate)
                continue
            existing = kept[duplicate_index]
            if candidate.tth and not existing.tth:
                kept[duplicate_index] = candidate
        return kept

    _ALT_BEFORE_YEAR = re.compile(
        r"^(?P<title>[^()\[\]{}]*?[^\s()\[\]{}])\s*\((?P<alt>[^()\[\]{}]*[^\W\d_][^()\[\]{}]*)\)\s*"
        r"(?P<year>\((?:19|20)\d{2}\)|\[(?:19|20)\d{2}\]|(?:19|20)\d{2}(?![0-9]))"
    )

    @classmethod
    def _arr_title(cls, name: str, known: set[str]) -> str | None:
        match = cls._ALT_BEFORE_YEAR.match(name)
        if not match:
            return None
        title, alt = match.group("title"), match.group("alt").strip()
        if re.fullmatch(r"[A-Z]{2,3}", alt):
            return None
        if normalize_text(title) not in known or normalize_text(f"{title} {alt}") in known:
            return None
        year = match.group("year").strip("()[]")
        return f"{title} ({year}) ({alt})" + name[match.end():]

    @staticmethod
    def _infer_languages(results: list[SearchResult], metadata: MediaMetadata) -> None:
        language_names = {
            "en": "English",
            "es": "Spanish",
            "ja": "Japanese",
            "fr": "French",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "ko": "Korean",
            "zh": "Chinese",
        }
        localized = normalize_text(metadata.localized_title or "")
        original = normalize_text(metadata.original_title or "")
        foreign = {normalize_text(t) for t in metadata.foreign_titles}
        localized_is_distinct = bool(localized and original and localized != original and localized not in foreign)
        # Palabras que declaran cada idioma. Cuenta como "otro idioma" todo lo que no sea el de los titulos
        # de TMDB (TMDB_LANGUAGE). Con castellano se mantiene el criterio de siempre: el ingles no lo impide.
        language_words = {
            "es": "spanish|espanol|castellano|latino",
            "en": "english|ingles",
            "de": "german|deutsch|ger",
            "ja": "japanese|jap|jpn",
            "fr": "french|francais|truefrench|vostfr|vff|fre",
            "it": "italian|italiano|ita",
            "pt": "portuguese|portugues",
            "ko": "korean|kor",
            "zh": "chinese|mandarin|cantonese",
            "xx": "russian|rus|polish|pol|dutch|swedish|danish|norwegian|finnish|nordic|czech|hungarian|turkish"
            "|hindi|thai|vietnamese|ukrainian|greek",
        }
        local_lang = metadata.localized_language or "es"
        local_name = language_names.get(local_lang)
        skip = {local_lang} | ({"en"} if local_lang == "es" else set())
        other_language = re.compile(
            r"\b(?:" + "|".join(words for code, words in language_words.items() if code not in skip) + r")\b"
        )
        localized_words = localized.split()

        for result in results:
            languages = detect_languages(result.name)
            words = normalize_text(result.name).split()
            localized_match = localized_is_distinct and any(
                words[index : index + len(localized_words)] == localized_words
                for index in range(min(3, len(words) - len(localized_words) + 1))
            )
            declares_other = bool(other_language.search(normalize_text(result.name)))
            if localized_match and local_name and local_name not in languages and not declares_other:
                languages.append(local_name)
            if localized_match and re.search(r"\bmulti\b", normalize_text(result.name)):
                original_language = language_names.get(metadata.original_language or "")
                if original_language and original_language not in languages:
                    languages.append(original_language)
            # Los del catálogo ya traen el idioma de su carpeta ("[Cast]"): se suman, no se sustituyen
            result.languages = list(dict.fromkeys(result.languages + languages))
            known = {normalize_text(t) for t in metadata.titles if t}
            renamed = SearchService._arr_title(result.name, known)
            if renamed:
                result.source_name = result.source_name or result.name
                result.name = renamed
