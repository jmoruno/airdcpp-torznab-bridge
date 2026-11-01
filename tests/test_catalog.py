from app.config import Settings
from app.services.catalog import CatalogService, useful_variants

MB = 1024 * 1024


def user(cid: str) -> dict:
    return {"user": {"cid": cid, "hub_url": "adcs://hub"}}


def folder(path: str, cid: str) -> dict:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    kind = {"id": "directory", "files": 74}
    return {"name": name, "path": path, "size": 20_000 * MB, "type": kind, "users": user(cid)}


def video(folder_path: str, name: str, cid: str, tth: str) -> dict:
    return {
        "name": name,
        "path": f"{folder_path}{name}",
        "size": 400 * MB,
        "tth": tth,
        "type": {"id": "file"},
        "_folder": folder_path,
        "users": user(cid),
    }


class FakeAirDC:
    def __init__(self, folders: list[dict], trees: dict[str, list[dict]], loose: list[dict] | None = None):
        self.folders = folders
        self.trees = trees
        self.loose = loose or []
        self.searches: list[str] = []

    async def directory_search(self, pattern: str, max_results: int | None = None) -> list[dict]:
        self.searches.append(pattern)
        return self.folders

    async def file_search(self, pattern: str, max_results: int | None = None) -> list[dict]:
        self.searches.append(f"ficheros:{pattern}")
        return self.loose

    async def browse_tree(self, item: dict, **limits) -> list[dict]:
        return self.trees.get(item["path"], [])


def settings(**values) -> Settings:
    return Settings(testing=True, airdcpp_url="http://airdcpp", **values)


def test_useful_variants_skip_supersets():
    assert useful_variants(["Hunter x Hunter (2011)", "Hunter × Hunter"]) == ["Hunter Hunter"]
    assert useful_variants(["Monstruo", "Monster"]) == ["Monstruo", "Monster"]
    assert useful_variants(["Hunter x Hunter", "75"]) == ["Hunter x Hunter"]


async def test_monster_catalog_uses_folder_language_and_drops_other_series():
    good = "/Series/Monster [2004] [Cast++Jap+Subs]/"
    scene = "/Anime/Monster (2004) {tvdb-74599}/Season 01/"
    other = "/Series/Monster The Ed Gein Story/"
    trees = {
        good: [video(good, f"Monster - {n:02d} [1080p].mkv", "A", f"A{n}") for n in range(1, 75)],
        "/Anime/Monster (2004) {tvdb-74599}/": [
            video(scene, f"Monster.S01E{n:02d}.720p.mkv", "B", f"B{n}") for n in range(1, 75)
        ],
        other: [video(other, "Monster.The.Ed.Gein.Story.S01E07.1080p.mkv", "C", "C7")],
    }
    airdc = FakeAirDC([folder(good, "A"), folder(scene, "B"), folder(other, "C")], trees)
    service = CatalogService(airdc, settings())
    catalog = await service.build("tvdb:74599", ["Monster"], "2004")

    assert {value.cid for value in catalog.files} == {"A", "B"}
    episode = service.results(catalog, 1, 7, (7,))
    names = sorted(result.name for result in episode)
    assert names == ["Monster (2004) S01E07 1080p SPANISH", "Monster (2004) S01E07 720p"]
    spanish = next(result for result in episode if "SPANISH" in result.name)
    assert spanish.languages == ["Spanish"] and spanish.tth == "A7"

    packs = service.results(catalog, 1, None, (), season_length=74)
    assert len(packs) == 2
    pack = next(result for result in packs if result.source_cid == "A")
    assert pack.name == "Monster (2004) S01 1080p SPANISH"
    assert len(pack.selected_files) == 74 and pack.item_type == "bundle"
    # Una temporada 1 de 58 capítulos no puede salir de una carpeta numerada hasta 74
    assert all(result.source_cid != "A" for result in service.results(catalog, 1, None, (), season_length=58))

    assert service.find(None, ["Monster"]) is catalog
    assert service.find("tvdb:1", ["Otra"]) is None


async def test_absolute_and_per_season_folders():
    absolute = "/Anime/Hunter x Hunter (2011) [Cast]/Temporada 2/"
    per_season = "/Series/Hunter x Hunter 2011/Temporada 2/"
    trees = {
        "/Anime/Hunter x Hunter (2011) [Cast]/": [
            video(absolute, f"Hunter x Hunter - {n:03d}.mkv", "A", f"A{n}") for n in range(59, 137)
        ],
        "/Series/Hunter x Hunter 2011/": [
            video(per_season, f"Hunter x Hunter - {n:02d}.mkv", "B", f"B{n}") for n in range(1, 79)
        ],
    }
    airdc = FakeAirDC([folder(absolute, "A"), folder(per_season, "B")], trees)
    service = CatalogService(airdc, settings())
    catalog = await service.build("tvdb:252322", ["Hunter x Hunter (2011)", "Hunter × Hunter"], "2011")

    assert airdc.searches == ["Hunter Hunter", "ficheros:Hunter Hunter"]
    # S02E37 = absoluto 95: el 095 de la carpeta absoluta y el 37 de la carpeta por temporada
    found = {result.tth for result in service.results(catalog, 2, 37, (95,))}
    assert found == {"A95", "B37"}
    # Petición solo con absoluto (Sonarr, series tipo Anime): no confunde el 37 de la temporada 2
    found = {result.tth for result in service.results(catalog, None, None, (37,))}
    assert found == set()
    result = service.results(catalog, None, None, (95,))[0]
    assert result.name == "Hunter x Hunter (2011) - 095 SPANISH"


async def test_search_service_answers_from_catalog_without_airdcpp():
    from typing import Any, cast

    from app.services.cache import AsyncTTLCache
    from app.services.metadata import MediaMetadata
    from app.services.search import SearchService

    good = "/Series/Monster [2004] [Cast++Jap+Subs]/"
    trees = {good: [video(good, f"Monster - {n:02d} [1080p].mkv", "A", f"A{n}") for n in range(1, 75)]}
    catalog_service = CatalogService(FakeAirDC([folder(good, "A")], trees), settings(catalog_verify_requests=0))
    await catalog_service.build("tvdb:74599", ["Monster"], "2004")

    class Metadata:
        async def details(self, *args):
            return MediaMetadata(["Monster"], "Monster", "Monster", "ja", {1: 74}, True, [], "es", "2004")

        async def episode_counts(self, *args):
            return {1: 74}

    class AirDC:
        calls = 0

        async def search(self, *args):
            self.calls += 1
            return []

    class Repository:
        async def save_release(self, result):
            pass

        async def save_hash(self, tth, release_id):
            pass

    air = AirDC()
    service = SearchService(
        cast(Any, air), cast(Any, Metadata()), cast(Any, Repository()), AsyncTTLCache(60, 1, 10),
        settings(catalog_verify_requests=0), catalog_service,
    )
    results = await service.search(None, "5000", None, None, "74599", 1, 7)
    assert air.calls == 0
    assert [result.name for result in results] == ["Monster (2004) S01E07 1080p SPANISH"]
    assert results[0].languages == ["Spanish"]


async def test_catalog_answers_alone_only_after_verification():
    from app.services.catalog import Catalog

    service = CatalogService(FakeAirDC([], {}), settings(catalog_verify_requests=2))
    catalog = Catalog(key="k", titles=["Show"], built_at=0)
    assert not service.trusted(catalog)
    service.verify(catalog, 0)
    service.verify(catalog, 3)  # la búsqueda normal trajo algo nuevo: vuelve a empezar
    assert catalog.verified == 0 and not service.trusted(catalog)
    service.verify(catalog, 0)
    service.verify(catalog, 0)
    assert service.trusted(catalog)


def test_series_root_is_the_highest_folder_with_the_title():
    from app.services.catalog import title_aliases

    service = CatalogService(FakeAirDC([], {}), settings())
    titles = ["Hunter x Hunter"]
    item = folder("/Anime/Hunter.x.Hunter.2011/Hunter.x.Hunter.S01.1080p-GHOST/Hunter.x.Hunter.E077.1080p-GHOST/", "G")
    root = service._series_root(item, title_aliases(titles), titles)
    assert root == (("G", "/Anime/Hunter.x.Hunter.2011/"), "Hunter.x.Hunter.2011")


async def test_season_one_marker_counts_as_absolute_and_catalog_knows_its_files():
    root = "/Anime/Hunter_x_Hunter_2011/"
    trees = {root: [video(root, f"Hunter_x_Hunter_2011_01x{n:03d}_Title.mkv", "A", f"A{n}") for n in range(1, 149)]}
    service = CatalogService(FakeAirDC([folder(root, "A")], trees), settings())
    catalog = await service.build("tvdb:1", ["Hunter x Hunter"], "2011")
    assert [result.tth for result in service.results(catalog, None, None, (77,))] == ["A77"]
    assert catalog.knows("A77") and not catalog.knows("ZZZ")
