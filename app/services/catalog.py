"""Catálogo por serie.

En vez de ir a AirDC++ por cada capítulo (12-20 s cada búsqueda, una detrás de otra), se busca la serie una vez,
se abren sus carpetas y se apunta cada vídeo con su temporada, capítulo, número absoluto e idioma. Las peticiones
siguientes de esa serie (Sonarr capítulo a capítulo, el addon) se contestan desde aquí al momento.

El idioma y la numeración se deciden sabiendo en qué carpeta está cada fichero: ``Monster - 01.mkv`` dentro de
``Monster [2004] [Cast++Jap+Subs]`` es el capítulo 1 de esa serie y está en castellano.
"""

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from app.config import Settings
from app.models import SearchResult
from app.services.airdcpp import AirDCClient
from app.utils.text import (
    absolute_episode,
    clean_search_pattern,
    detect_languages,
    episode_marker,
    normalize_text,
    search_variants,
    strip_diacritics,
    title_roots,
)

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = (".mkv", ".avi", ".mp4", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg", ".ts")
MIN_VIDEO_SIZE = 50 * 1024 * 1024
# "Temporada 2", "Season 02", "S02", "T2", "Staffel 2" en el nombre de una carpeta (ya normalizado)
FOLDER_SEASON = re.compile(r"\b(?:temporada|season|staffel|temp|s|t)\s*0?(\d{1,2})\b")
# "01 - Dr Tenma", "Capitulo 7", "E07": el número al principio cuando el fichero no lleva el título
LOOSE_NUMBER = re.compile(r"^(?:(?:capitulo|cap|episodio|episode|ep|e)\s*)?0*(\d{1,4})\b")


@dataclass
class CatalogFile:
    name: str
    size: int
    tth: str
    cid: str
    hub_url: str
    path: str
    folder: str
    series_folder: str
    languages: list[str]
    season: int | None = None  # S01E07 / 1x07 en el nombre
    episode: int | None = None
    folder_season: int | None = None  # "Temporada 2" en alguna carpeta
    number: int | None = None  # número tras el título: "Monster - 07"
    absolute_folder: bool = True  # la carpeta numera en absoluto, no desde 1 en cada temporada


@dataclass
class Catalog:
    key: str
    titles: list[str]
    built_at: float
    files: list[CatalogFile] = field(default_factory=list)
    folders: int = 0
    # Por qué puede faltar algo: búsqueda llena, carpetas de más o sin terminar de recorrer
    gaps: list[str] = field(default_factory=list)
    # Peticiones seguidas en las que la búsqueda normal no aportó nada que no tuviera el catálogo
    verified: int = 0

    @property
    def complete(self) -> bool:
        return not self.gaps


def title_aliases(titles: list[str]) -> list[list[str]]:
    """Títulos como listas de palabras, sin años, del más largo al más corto."""
    aliases = [normalize_text(clean_search_pattern(title)) for title in titles]
    aliases += [normalize_text(root) for root in title_roots(titles)]
    aliases = [re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in aliases]
    unique = list(dict.fromkeys(alias for alias in aliases if alias))
    return sorted((alias.split() for alias in unique), key=len, reverse=True)


def starts_with_title(name: str, aliases: list[list[str]]) -> bool:
    words = normalize_text(name.replace("_", " ")).split()
    return any(
        words[index : index + len(alias)] == alias for alias in aliases for index in range(min(3, len(words)))
    )


def useful_variants(titles: list[str]) -> list[str]:
    """Variantes de búsqueda sin las que no pueden encontrar nada nuevo.

    AirDC++ exige todas las palabras: una variante con todas las palabras de otra (y alguna más) solo devuelve
    una parte de lo que ya trae la otra. Se buscan primero las de menos palabras, que son las que más encuentran.
    """
    latin = [
        value
        for value in search_variants(titles)
        if all(char.isascii() or not char.isalpha() for char in strip_diacritics(value))
        and sum(char.isalpha() for char in value) >= 3  # "75" no es un título
    ]
    kept: list[tuple[set[str], str]] = []
    for variant in sorted(latin, key=lambda value: len(normalize_text(value).split())):
        words = set(normalize_text(variant).split())
        if words and not any(previous <= words for previous, _ in kept):
            kept.append((words, variant))
    return [variant for _, variant in kept]


class CatalogService:
    def __init__(self, airdcpp: AirDCClient, settings: Settings):
        self.airdcpp = airdcpp
        self.settings = settings
        self.catalogs: OrderedDict[str, Catalog] = OrderedDict()
        self.aliases: dict[str, str] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    # --- consulta ---------------------------------------------------------------------------------------------

    def find(self, key: str | None, titles: list[str]) -> Catalog | None:
        """Catálogo vigente de la serie, por su id o por cualquiera de sus títulos."""
        if not self.settings.catalog_enabled:
            return None
        candidates = [key] if key else []
        candidates += [self.aliases.get(" ".join(alias)) for alias in title_aliases(titles)]
        for candidate in candidates:
            catalog = self.catalogs.get(candidate) if candidate else None
            if catalog and time.monotonic() - catalog.built_at < self.settings.catalog_ttl:
                return catalog
        return None

    def trusted(self, catalog: Catalog) -> bool:
        """El catálogo contesta solo cuando ha demostrado que no le falta nada (CATALOG_VERIFY_REQUESTS)."""
        return catalog.verified >= self.settings.catalog_verify_requests

    def verify(self, catalog: Catalog, new: int) -> None:
        """Resultado de comparar con la búsqueda normal: sin nada nuevo suma; con algo nuevo vuelve a empezar."""
        before = self.trusted(catalog)
        catalog.verified = 0 if new else catalog.verified + 1
        if self.trusted(catalog) and not before:
            logger.info("Catálogo de %r verificado: contesta solo a partir de ahora", catalog.titles[0])

    def ensure(self, key: str | None, titles: list[str], year: str | None) -> None:
        """Arma el catálogo en segundo plano si no hay uno vigente ni se está armando ya."""
        if not self.settings.catalog_enabled or not key or not titles:
            return
        if self.find(key, titles) or key in self.tasks:
            return
        task = asyncio.create_task(self._build_logged(key, titles, year))
        self.tasks[key] = task
        task.add_done_callback(lambda _: self.tasks.pop(key, None))

    def results(
        self,
        catalog: Catalog,
        season: int | None,
        episode: int | None,
        absolutes: tuple[int, ...],
        season_length: int | None = None,
    ) -> list[SearchResult]:
        if season is not None and episode is None:
            return self._season_packs(catalog, season, season_length)
        output: list[SearchResult] = []
        for value in catalog.files:
            if not self._matches(value, season, episode, absolutes):
                continue
            base = self._display_base(value.series_folder)
            if season is not None and episode is not None:
                display = f"{base} S{season:02d}E{episode:02d}"
            else:
                number = value.number if value.number in absolutes else absolutes[0]
                display = f"{base} - {number:03d}"
            suffix = self._suffix(value)
            output.append(
                SearchResult(
                    release_id=hashlib.sha1(value.tth.encode()).hexdigest(),
                    name=f"{display} {suffix}".strip(),
                    size=value.size,
                    tth=value.tth,
                    item_type="file",
                    query=catalog.titles[0],
                    languages=list(value.languages),
                    source_name=value.name,
                    source_path=value.path,
                    source_cid=value.cid,
                    source_hub_url=value.hub_url,
                )
            )
        return output

    @staticmethod
    def _matches(value: CatalogFile, season: int | None, episode: int | None, absolutes: tuple[int, ...]) -> bool:
        if value.season is not None:
            return season is not None and value.season == season and value.episode == episode
        if value.number is None:
            return False
        if value.number in absolutes and (value.absolute_folder or value.folder_season == 1):
            return True  # en la temporada 1 el número de capítulo y el absoluto coinciden
        return (
            not value.absolute_folder
            and season is not None
            and value.folder_season == season
            and value.number == episode
        )

    def _season_packs(self, catalog: Catalog, season: int, season_length: int | None) -> list[SearchResult]:
        groups: dict[tuple[str, str], list[tuple[int, CatalogFile]]] = {}
        for value in catalog.files:
            if value.season is not None:
                number = value.episode if value.season == season else None
            elif not value.absolute_folder:
                number = value.number if value.folder_season == season else None
            else:
                # Numeración absoluta: solo vale como temporada 1 (sin pasarse de sus capítulos)
                number = value.number if season == 1 else None
            if number:
                groups.setdefault((value.cid, value.folder), []).append((number, value))
        output: list[SearchResult] = []
        for (cid, folder), entries in groups.items():
            numbers = sorted({number for number, _ in entries})
            if len(numbers) < 2 or numbers != list(range(1, numbers[-1] + 1)) or len(numbers) != len(entries):
                continue
            if season_length and numbers[-1] > season_length:
                continue
            files = [value for _, value in sorted(entries, key=lambda pair: pair[0])]
            first = files[0]
            languages = sorted(set.intersection(*(set(value.languages) for value in files)))
            suffix = AirDCClient._common_technical_suffix([f"{value.name} {value.path}" for value in files])
            output.append(
                SearchResult(
                    release_id=hashlib.sha1(f"catalogo:{cid}:{folder}:{season}".encode()).hexdigest(),
                    name=f"{self._display_base(first.series_folder)} S{season:02d} {suffix}".strip(),
                    size=sum(value.size for value in files),
                    item_type="bundle",
                    query=catalog.titles[0],
                    languages=languages,
                    source_name=folder.rstrip("/").rsplit("/", 1)[-1],
                    source_path=folder,
                    source_cid=cid,
                    source_hub_url=first.hub_url,
                    selected_files=[{"name": value.name, "size": value.size, "tth": value.tth} for value in files],
                )
            )
        return output

    @staticmethod
    def _display_base(series_folder: str) -> str:
        """"Monster [2004] [Cast]" -> "Monster (2004)": título y año, sin etiquetas que líen a Sonarr."""
        year = re.search(r"\b((?:19|20)\d{2})\b", series_folder)
        base = re.sub(r"[\[{(][^\]})]*[\]})]", " ", series_folder)
        base = re.sub(r"\b(?:19|20)\d{2}\b", " ", base.replace("_", " ").replace(".", " "))
        base = " ".join(base.split()) or series_folder
        return f"{base} ({year.group(1)})" if year else base

    @staticmethod
    def _suffix(value: CatalogFile) -> str:
        return AirDCClient._common_technical_suffix([f"{value.name} {value.path}"])

    # --- construcción -----------------------------------------------------------------------------------------

    async def _build_logged(self, key: str, titles: list[str], year: str | None) -> None:
        try:
            await self.build(key, titles, year)
        except Exception as exc:  # noqa: BLE001 - en segundo plano: se registra y se sigue sin catálogo
            logger.warning("No se pudo armar el catálogo de %r: %s", titles[0], exc)

    async def build(self, key: str, titles: list[str], year: str | None) -> Catalog:
        start = time.monotonic()
        aliases = title_aliases(titles)
        folders: dict[tuple[str, str], tuple[dict, str]] = {}
        loose: list[dict] = []
        gaps: list[str] = []
        # El catálogo pide hasta 5000 resultados (la búsqueda normal, SEARCH_MAX_RESULTS): con títulos de anime
        # largos 1000 se quedan cortos y faltarían carpetas y ficheros sueltos
        limit = max(5000, self.settings.search_max_results)
        for variant in useful_variants(titles)[:3]:
            raw = await self.airdcpp.directory_search(variant, limit)
            if len(raw) >= limit and year and year not in variant:
                # Título genérico: los primeros 1000 son de otras cosas. Con el año salen los de la serie,
                # y se suman a lo ya encontrado (sin sustituirlo).
                logger.info("Catálogo: %r llena el máximo, se añade %r", variant, f"{variant} {year}")
                with_year = await self.airdcpp.directory_search(f"{variant} {year}", limit)
                if len(with_year) >= limit:
                    gaps.append(f"carpetas de {variant!r} {year}")
                raw += with_year
            elif len(raw) >= limit:
                gaps.append(f"carpetas de {variant!r}")
            for item in raw:
                root = self._series_root(item, aliases, titles)
                if root:
                    folders.setdefault(root[0], (item, root[1]))
        if useful_variants(titles):
            loose = await self.airdcpp.file_search(useful_variants(titles)[0], limit)
            if len(loose) >= limit:
                gaps.append("ficheros sueltos")
        candidates = self._top_folders(folders)
        if len(candidates) < len({root for root in folders}) and len(candidates) >= self.settings.catalog_max_folders:
            gaps.append(f"más de {self.settings.catalog_max_folders} carpetas")
        catalog = Catalog(key=key, titles=titles, built_at=time.monotonic(), gaps=gaps)
        files = await self._browse(candidates, gaps)
        for item in loose:
            if not starts_with_title(str(item.get("name") or ""), aliases):
                continue
            folder = str(item.get("path") or "").rsplit("/", 1)[0] + "/"
            parent = folder.rstrip("/").rsplit("/", 1)[-1]
            series_folder = parent if starts_with_title(parent, aliases) else titles[0]
            files.append({**item, "_folder": folder, "_series_folder": series_folder})
        seen: set[tuple[str, str]] = set()
        for item in files:
            entry = self._entry(item, aliases)
            if entry and (entry.cid, entry.tth) not in seen:
                seen.add((entry.cid, entry.tth))
                catalog.files.append(entry)
        self._mark_numbering(catalog.files)
        catalog.folders = len(candidates)
        catalog.built_at = time.monotonic()
        self.catalogs[key] = catalog
        self.catalogs.move_to_end(key)
        for alias in aliases:
            self.aliases[" ".join(alias)] = key
        while len(self.catalogs) > 50:
            old_key, _ = self.catalogs.popitem(last=False)
            self.aliases = {alias: value for alias, value in self.aliases.items() if value != old_key}
        logger.info(
            "Catálogo de %r: %d carpetas, %d vídeos (%d en castellano) en %.0f s; %s",
            titles[0],
            len(candidates),
            len(catalog.files),
            sum("Spanish" in value.languages for value in catalog.files),
            time.monotonic() - start,
            "completo" if catalog.complete else "incompleto: " + ", ".join(catalog.gaps),
        )
        return catalog

    def _series_root(
        self, item: dict, aliases: list[list[str]], titles: list[str]
    ) -> tuple[tuple[str, str], str] | None:
        """La carpeta de la serie: la del resultado o una de sus dos carpetas padre, si empieza por el título."""
        kind = item.get("type") or {}
        if not isinstance(kind, dict) or kind.get("id") != "directory":
            return None
        users = item.get("users")
        cid = str((users.get("user") or {}).get("cid") or "") if isinstance(users, dict) else ""
        path = str(item.get("path") or "")
        parts = [part for part in path.split("/") if part]
        if not cid or not parts:
            return None
        # La más alta de las tres últimas que empiece por el título: en "Serie.2011/Serie.S01/Serie.E077/" se
        # recorre la de la serie entera, no una carpeta por capítulo
        for index in range(max(0, len(parts) - 3), len(parts)):
            if starts_with_title(parts[index], aliases) and not self._other_series(parts[index], titles):
                root = "/" + "/".join(parts[: index + 1]) + "/"
                return (cid, root), parts[index]
        return None

    @staticmethod
    def _other_series(folder: str, titles: list[str]) -> bool:
        """"Monster The Ed Gein Story" no es "Monster": mismo filtro que en la búsqueda normal."""
        from app.services.search import SearchService  # import tardío: search importa este módulo

        full = [normalize_text(clean_search_pattern(title)) for title in titles]
        full = list(dict.fromkeys(re.sub(r"\b(?:19|20)\d{2}\b", "", alias).strip() for alias in full))
        full = [alias for alias in full if alias]
        roots = [alias for alias in (normalize_text(root) for root in title_roots(titles)) if alias not in full]
        unbracketed = re.sub(r"[\[{(][^\]})]*[\]})]", " ", folder)
        words = normalize_text(f"{unbracketed} S01".replace("_", " ")).split()
        return SearchService._other_series(words, full, roots, titles)

    def _top_folders(self, folders: dict[tuple[str, str], tuple[dict, str]]) -> list[tuple[dict, str]]:
        """Una entrada por carpeta raíz (sin sus subcarpetas, que ya se recorren), las más grandes primero."""
        roots = sorted(folders.items(), key=lambda pair: len(pair[0][1]))
        kept: dict[tuple[str, str], tuple[dict, str]] = {}
        for (cid, root), (item, name) in roots:
            if any(cid == other_cid and root.startswith(other_root) for other_cid, other_root in kept):
                continue
            kept[(cid, root)] = ({**item, "path": root, "name": name}, name)
        ordered = sorted(kept.values(), key=lambda pair: -int(float(pair[0].get("size", 0) or 0)))
        return ordered[: self.settings.catalog_max_folders]

    async def _browse(self, candidates: list[tuple[dict, str]], gaps: list[str]) -> list[dict]:
        semaphore = asyncio.Semaphore(6)

        async def browse(item: dict, name: str) -> list[dict]:
            async with semaphore:
                values = await self.airdcpp.browse_tree(item, max_depth=2, max_dirs=200)
                return [{**value, "_series_folder": name} for value in values]

        tasks = [asyncio.create_task(browse(item, name)) for item, name in candidates]
        if not tasks:
            return []
        done, pending = await asyncio.wait(tasks, timeout=self.settings.catalog_build_timeout)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            gaps.append(f"{len(pending)} carpetas sin recorrer")
        files: list[dict] = []
        for task in tasks:
            if task in done and not task.cancelled() and task.exception() is None:
                files.extend(task.result())
        return files

    @staticmethod
    def _entry(item: dict, aliases: list[list[str]]) -> CatalogFile | None:
        name = str(item.get("name") or "")
        size = int(float(item.get("size", 0) or 0))
        tth = str(item.get("tth") or "")
        if not name.lower().endswith(VIDEO_EXTENSIONS) or size < MIN_VIDEO_SIZE or not tth:
            return None
        users = item.get("users")
        user = (users.get("user") or {}) if isinstance(users, dict) else {}
        folder = str(item.get("_folder") or "")
        series_folder = str(item.get("_series_folder") or "") or name
        # Carpetas desde la de la serie hacia abajo: de ahí salen la temporada y el idioma de la carpeta
        parts = [part for part in folder.split("/") if part]
        start = max((index for index, part in enumerate(parts) if part == series_folder), default=len(parts) - 1)
        own_folders = parts[max(0, start) :]
        # Dentro de "Hunter x Hunter/" puede haber "Hunter x Hunter (1999)/" y "(2011)/": cuenta la más concreta
        series_folder = next(
            (part for part in reversed(own_folders) if starts_with_title(part, aliases)), series_folder
        )
        languages = set(detect_languages(name))
        for part in own_folders:
            languages.update(detect_languages(part))
        entry = CatalogFile(
            name=name,
            size=size,
            tth=tth,
            cid=str(user.get("cid") or ""),
            hub_url=str(user.get("hub_url") or ""),
            path=str(item.get("path") or f"{folder}{name}"),
            folder=folder,
            series_folder=series_folder,
            languages=sorted(languages),
        )
        marker = episode_marker(name)
        if marker:
            entry.season, entry.episode = marker
            return entry if entry.episode else None
        for part in reversed(own_folders):
            found = FOLDER_SEASON.search(normalize_text(part))
            if found:
                entry.folder_season = int(found.group(1))
                break
        for alias in aliases:
            entry.number = absolute_episode(name, " ".join(alias))
            if entry.number:
                break
        if not entry.number:
            stem = re.sub(r"[\[({][^\])}]*[\])}]", " ", name.rsplit(".", 1)[0])
            loose = LOOSE_NUMBER.match(normalize_text(stem))
            entry.number = int(loose.group(1)) if loose and 0 < int(loose.group(1)) < 2000 else None
        return entry if entry.number else None

    @staticmethod
    def _mark_numbering(files: list[CatalogFile]) -> None:
        """Una carpeta con "Temporada 2" cuyos números empiezan en 1 numera por temporada; si no, en absoluto."""
        groups: dict[tuple[str, str], list[CatalogFile]] = {}
        for value in files:
            if value.season is None and value.number:
                groups.setdefault((value.cid, value.folder), []).append(value)
        for entries in groups.values():
            first = min(value.number or 0 for value in entries)
            per_season = all(value.folder_season for value in entries) and first == 1
            for value in entries:
                value.absolute_folder = not per_season
