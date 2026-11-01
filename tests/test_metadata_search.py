from typing import Any, cast

import httpx

from app.config import Settings
from app.models import SearchResult
from app.services.cache import AsyncTTLCache
from app.services.metadata import MediaMetadata, MetadataClient
from app.services.search import SearchService


async def test_tmdb_metadata_is_optional_and_deduplicated():
    def handler(request: httpx.Request):
        assert request.url.path == "/3/movie/10"
        return httpx.Response(
            200,
            json={
                "title": "Título",
                "original_title": "Title",
                "original_language": "en",
                "alternative_titles": {"titles": [{"iso_3166_1": "ES", "title": "Título"}]},
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = MetadataClient(http, "key")
    assert await client.titles("Original query", tmdb_id="10", media_type="movie") == [
        "Título",
        "Title",
        "Original query",
    ]
    assert await client.titles("Original query", tmdb_id="10", media_type="movie") == [
        "Título",
        "Title",
        "Original query",
    ]
    await http.aclose()


async def test_tvmaze_aliases_and_metadata_failures():
    def handler(request: httpx.Request):
        if request.url.path == "/lookup/shows":
            return httpx.Response(200, json={"id": 2, "name": "Show"})
        if request.url.path == "/shows/2/akas":
            return httpx.Response(
                200,
                json=[
                    {"name": "Serie", "country": {"code": "ES"}},
                    {"name": "Ignored", "country": {"code": "US"}},
                ],
            )
        return httpx.Response(500)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = MetadataClient(http)
    assert await client.titles("Query", tvdb_id="22", media_type="tv") == ["Show", "Serie", "Query"]
    assert await MetadataClient(http, "key")._tmdb_titles(None, "missing", "movie") == []
    await http.aclose()


async def test_search_service_persists_results_and_uses_cache():
    class Metadata:
        async def details(self, *args):
            return MediaMetadata(["Movie"])

    class AirDC:
        calls = 0

        async def search(self, variants, season, extensions):
            self.calls += 1
            return [
                SearchResult(
                    release_id="a" * 40,
                    name="Movie.2024.mkv",
                    size=100 * 1024 * 1024,
                    tth="TTH",
                )
            ]

    class Repository:
        releases = []
        hashes = []

        async def save_release(self, result):
            self.releases.append(result)

        async def save_hash(self, tth, release_id):
            self.hashes.append((tth, release_id))

    air = AirDC()
    repository = Repository()
    service = SearchService(
        cast(Any, air),
        cast(Any, Metadata()),
        cast(Any, repository),
        AsyncTTLCache(60, 1, 10),
        Settings(testing=True),
    )
    first = await service.search("Movie 2024", "2000", None, None, None, None, None)
    second = await service.search("Movie 2024", "2000,2040", "tt1", "10", None, None, None)
    assert first == second
    assert air.calls == 2
    assert repository.hashes == [("TTH", "a" * 40)]


def test_relevance_filter_rejects_substrings_wrong_year_and_small_files():
    mib = 1024 * 1024
    results = [
        SearchResult(release_id="1", name="Her.2013.1080p.Dual.mkv", size=900 * mib, tth="A"),
        SearchResult(release_id="2", name="Together.2013.mkv", size=900 * mib, tth="B"),
        SearchResult(release_id="3", name="Her.2025.mkv", size=900 * mib, tth="C"),
        SearchResult(release_id="4", name="Her.2013.sample.mkv", size=20 * mib, tth="D"),
        SearchResult(release_id="5", name="Her 3 The Return 2013.mkv", size=900 * mib, tth="E"),
    ]
    filtered = SearchService._filter_and_rank(results, ["Her"], "2013", None, None)
    assert [result.release_id for result in filtered] == ["1"]


def test_deduplicates_matching_file_and_directory_preferring_tth():
    gib = 1024**3
    results = [
        SearchResult(release_id="dir", name="Atlantis El imperio perdido (2001)", size=6 * gib, item_type="directory"),
        SearchResult(
            release_id="file",
            name="Atlantis El imperio perdido (2001).mkv",
            size=6 * gib + 10 * 1024 * 1024,
            item_type="file",
            tth="TTH",
        ),
    ]
    assert [result.release_id for result in SearchService._deduplicate_file_directories(results)] == ["file"]

    tagged = [
        SearchResult(release_id="file", name="Atlantis (2001).mkv", size=2 * gib, tth="TTH"),
        SearchResult(
            release_id="dir",
            name="Atlantis (2001) {tmdb-10865}",
            size=2 * gib,
            item_type="directory",
        ),
    ]
    assert [result.release_id for result in SearchService._deduplicate_file_directories(tagged)] == ["file"]


async def test_adaptive_search_uses_short_title_and_rejects_small_movie_directory():
    mib = 1024 * 1024

    class Metadata:
        async def details(self, *args):
            return MediaMetadata(
                ["Atlantis: El imperio perdido", "Atlantis: The Lost Empire"],
                "Atlantis: El imperio perdido",
                "Atlantis: The Lost Empire",
                "en",
            )

    class AirDC:
        variants = []

        async def search(self, variants, season, extensions):
            variant = variants[0]
            self.variants.append(variant)
            assert variant == "Atlantis 2001"
            return [
                SearchResult(
                    release_id="soundtrack",
                    name="2001 ATLANTIS. THE LOST EMPIRE. James Newton Howard",
                    size=171 * mib,
                    item_type="directory",
                ),
                *[
                    SearchResult(
                        release_id=str(index),
                        name=f"Atlantis.2001.1080p.Part{index}.mkv",
                        size=900 * mib,
                        tth=f"TTH{index}",
                    )
                    for index in range(5)
                ],
            ]

    class Repository:
        async def save_release(self, result):
            pass

        async def save_hash(self, tth, release_id):
            pass

    air = AirDC()
    service = SearchService(
        cast(Any, air),
        cast(Any, Metadata()),
        cast(Any, Repository()),
        AsyncTTLCache(60, 1, 10),
        Settings(testing=True),
    )
    results = await service.search("Atlantis: The Lost Empire 2001", "2000", None, "10865", None, None, None)
    assert len(results) == 5
    assert all(result.release_id != "soundtrack" for result in results)
    assert air.variants == ["Atlantis 2001"]


def test_language_inference_requires_distinct_localized_title_and_handles_multi():
    results = [
        SearchResult(release_id="1", name="Atlantis El imperio perdido (2001).mkv", size=1),
        SearchResult(release_id="2", name="Atlantis El imperio perdido (2001) Multi.mkv", size=1),
    ]
    SearchService._infer_languages(
        results,
        MediaMetadata(
            ["Atlantis: El imperio perdido", "Atlantis: The Lost Empire"],
            "Atlantis: El imperio perdido",
            "Atlantis: The Lost Empire",
            "en",
        ),
    )
    assert results[0].languages == ["Spanish"]
    assert results[1].languages == ["Spanish", "English"]

    ambiguous = [SearchResult(release_id="x", name="X.2022.Multi.mkv", size=1)]
    SearchService._infer_languages(ambiguous, MediaMetadata(["X"], "X", "X", "en"))
    assert ambiguous[0].languages == []


def test_other_series_with_same_first_word_is_rejected():
    def result(name):
        return SearchResult(release_id=name.encode().hex()[:40].ljust(40, "0"), name=name, size=500 * 1024 * 1024)

    names = [
        "Monster.The.Ed.Gein.Story.S01E07.MULTi.1080p.NF.WEB-DL.mkv",
        "Monster.High.S01.DUTCH.1080p.WEB.h264",
        "Monster 2004 TVDB-74599 S01 480p WEBDL",
        "Monster S01 Temporada 1",
        "Monster HDTV Castellano S01",
        "Monster Serie Completa Castellano Temporada 1",
    ]
    accepted = SearchService._filter_and_rank([result(name) for name in names], ["Monster"], None, 1, None, "tv")
    assert sorted(value.name for value in accepted) == sorted(names[2:])

    frieren = [result("Frieren - Tras el final del viaje S01E07 1080p.mkv")]
    titles = ["Frieren: Beyond Journey's End", "Sousou no Frieren"]
    assert SearchService._filter_and_rank(frieren, titles, None, 1, 7, "tv") == frieren
    office = [result("The Office US S01E01 720p.mkv")]
    assert SearchService._filter_and_rank(office, ["The Office (US)"], None, 1, 1, "tv") == office
    movie = [result("Monster The Ed Gein Story S01 2160p")]
    assert SearchService._filter_and_rank(movie, ["Monster"], None, None, None, "movie") == movie


def test_same_title_from_another_year_or_id_is_dropped():
    def result(name):
        return SearchResult(release_id=name.encode().hex()[:40].ljust(40, "0"), name=name, size=1)

    names = [
        "Monster (2022) {Tvdb=389492} S01 1080p",
        "Monster [2004] S01 1080p SPANISH",
        "Monster 1983 - Staffel 01-03",
        "Monster 2004 TVDB-74599 S01",
        "Monster S01",
    ]
    kept = SearchService._same_series([result(name) for name in names], ["Monster"], "74599", None, "2004")
    assert [value.name for value in kept] == [names[1], names[3], names[4]]
