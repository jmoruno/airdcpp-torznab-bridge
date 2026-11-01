# AirDC++ Torznab Bridge

[![Build](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/docker.yml) [![CodeQL](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/codeql.yml) [![Trivy](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/trivy.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/trivy.yml) [![Release](https://img.shields.io/github/v/release/jmoruno/airdcpp-torznab-bridge)](https://github.com/jmoruno/airdcpp-torznab-bridge/releases/latest) [![Docker pulls](https://img.shields.io/docker/pulls/jmorunofdz/airdcpp-torznab-bridge)](https://hub.docker.com/r/jmorunofdz/airdcpp-torznab-bridge) [![Image size](https://img.shields.io/docker/image-size/jmorunofdz/airdcpp-torznab-bridge/stable)](https://hub.docker.com/r/jmorunofdz/airdcpp-torznab-bridge) [![License](https://img.shields.io/github/license/jmoruno/airdcpp-torznab-bridge)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/jmoruno)

[Español](README.md) · **English**

Bridge between **Radarr / Sonarr** and **AirDC++** hubs:

- **Torznab indexer**: Radarr and Sonarr search your hubs as if they were a tracker.
- **qBittorrent-compatible download client**: they start downloads in AirDC++ and track their progress.

Fork of [Antaneyes/airdcpp-torznab-bridge](https://github.com/Antaneyes/airdcpp-torznab-bridge), based on its `v2.0.0-beta.4`, with fixes for Spanish hubs, anime and the [airdcpp-stream](https://github.com/jmoruno/airdcpp-stream) addon. Licensed under [GPL-3.0](LICENSE), like the original.

> Use it only inside your own network. Do not expose it directly to the Internet.

## Contents

- [Docker image](#docker-image)
- [Deploying on Unraid / Portainer](#deploying-on-unraid--portainer)
- [Setting up Radarr and Sonarr](#setting-up-radarr-and-sonarr)
- [Environment variables](#environment-variables)
- [Changes from the original](#changes-from-the-original)
- [API](#api)
- [Troubleshooting](#troubleshooting)
- [Development and releases](#development-and-releases)
- [License](#license)
- [Disclaimer](#disclaimer)

## Docker image

| Tag | Channel | Use |
| --- | --- | --- |
| `stable` / `latest` | stable | Production: latest stable release |
| `X.Y` / `X.Y.Z` (e.g. `2.1.0`) | stable | Pin a specific version or roll back |
| `beta` / `X.Y.Z-rc.N` | beta | Release candidates, before going stable |
| `dev` and other branches | development | Test changes without touching production |
| `sha-<commit>` | — | One exact build |

Image: `jmorunofdz/airdcpp-torznab-bridge` (`linux/amd64`).

## Deploying on Unraid / Portainer

It runs as **two containers from the same image**, one for movies and one for TV, so each one saves to its own folder and keeps its own cache.

| Container | Port | Folder (`SAVE_PATH`) | Categories |
| --- | --- | --- | --- |
| `airdcpp-bridge-movies` | 8001 | `/Downloads` | `radarr,radarr4k,stremio` |
| `airdcpp-bridge-series` | 8002 | `/DownloadsSeries` | `sonarr,sonarr4k,stremio` |

1. Create a stack from [`docker-compose.yml`](docker-compose.yml).
2. In the stack variables, load a `.env` with the values from [`.env.example`](.env.example): passwords, keys and URLs.
3. Deploy and check it works:

```bash
curl http://SERVER-IP:8001/health/ready
curl http://SERVER-IP:8002/health/ready
```

**Updating:** when there is a new release, in Portainer use *Update the stack* with *Re-pull image*.

**Testing a branch:** create a separate stack with the `:dev` image (or another branch), different ports (e.g. 8011/8012) and different container and volume names, so production is not touched.

**Data:** each container keeps its SQLite database in a volume (`bridge-data`, `bridge-series-data`). If you rename the stack, Docker creates new volumes and the cache and the tracking of running downloads are lost.

**Paths:** `SAVE_PATH` is the folder **as AirDC++ sees it**, not as the bridge sees it. The bridge does not need the downloads mounted.

## Setting up Radarr and Sonarr

### Indexer (Torznab)

| Field | Radarr | Sonarr |
| --- | --- | --- |
| URL | `http://IP:8001/torznab` | `http://IP:8002/torznab` |
| API Path | `/api` | `/api` |
| API Key | `BRIDGE_API_KEY` | `BRIDGE_API_KEY` |
| Categories | `2000`, `2040` | `5000`, `5040` |
| RSS | off (hubs have no RSS) | off |
| Download client | this bridge's client | this bridge's client |

Link the indexer to its client in *Advanced settings → Download client*. Otherwise Radarr or Sonarr may send the bridge's results to another torrent client.

### Download client (qBittorrent)

| Field | Value |
| --- | --- |
| Host / Port | Server IP and `8001` (Radarr) or `8002` (Sonarr) |
| Username / Password | `BRIDGE_USERNAME` / `BRIDGE_PASSWORD` |
| Category | `radarr` / `sonarr` (must be listed in `DOWNLOAD_CATEGORIES`) |
| Sequential download, first and last piece | off |

If Radarr or Sonarr see the downloads folder under a different path than AirDC++, add a *Remote Path Mapping*:

- **Host:** the same one you set in the client.
- **Remote:** `SAVE_PATH`.
- **Local:** the path mounted in Radarr or Sonarr.

### Profiles and custom formats

Without this, Radarr and Sonarr grab releases in other languages or full Bluray discs (`BDMV` folders, `.iso`), which cannot be played or imported properly. The formats are ready to import from [`arr/`](arr): in Radarr or Sonarr, **Settings → Custom Formats → +** → **Import** and paste the JSON. The examples are for Spanish; see the end of this section for English.

**Radarr** (profiles have a language):

| Setting | Value |
| --- | --- |
| Profile → Language | **Spanish** (or **English**) |
| [`Bluray`](arr/radarr/bluray.json) format | **−10000**: blocks discs only (`bdmv`, `m2ts`, `iso`, `bd25/50/66/100`, `full disc`, `complete`). Remuxes and rips (`BDRip`, `BluRay x264`) are allowed |
| Minimum score | `0` |

**Sonarr** (v4 has no profile language, so it is all custom formats):

| Format | Score | Matches |
| --- | --- | --- |
| [`Español (idioma)`](arr/sonarr/espanol-idioma.json) | **+100** | Detected language Spanish (sent by the bridge) |
| [`Español (título)`](arr/sonarr/espanol-titulo.json) | **+100** | Name contains `castellano`, `spanish`, `español`, `dual`, `multi`, `temporada`, `cap`… |
| [`Bluray`](arr/sonarr/bluray.json) | **−10000** | Discs. Unlike Radarr it uses `complete.?blu.?ray` instead of `complete`, because for TV "COMPLETE" also marks regular season packs |
| **Profile minimum score** | **100** | Anything without Spanish is rejected |

> Copy the expressions from the JSON exactly: a leading space (`"   \b(…"`) makes them never match, with no error shown.

For English hubs: set the Radarr profile language to **English**, in Sonarr replace `Español (idioma)` with your language (or remove it along with the minimum score) and set `TMDB_LANGUAGE=en-US` in the bridge.

## Environment variables

### Required

| Variable | Use |
| --- | --- |
| `AIRDCPP_URL` | AirDC++ web API, e.g. `http://host.docker.internal:54345` |
| `AIRDCPP_USER`, `AIRDCPP_PASS` | AirDC++ user. Needs permissions for hubs, search, file lists and queue |
| `BRIDGE_API_KEY` | Torznab indexer key |
| `BRIDGE_USERNAME`, `BRIDGE_PASSWORD` | qBittorrent client login |
| `PUBLIC_URL` | URL Radarr and Sonarr use to reach this container (download links use it) |
| `SAVE_PATH` | Destination folder as AirDC++ sees it |

### Recommended

| Variable | Default | Use |
| --- | --- | --- |
| `TMDB_API_KEY` | — | Localized and alternative titles, original language and anime detection. Without it, only the title sent by Arr is searched |
| `TMDB_LANGUAGE` | `es-ES` | Language of TMDB titles, and the language assumed when a name starts with that title. Use `en-US` for English hubs (`fr-FR`, `de-DE`…) |
| `DOWNLOAD_CATEGORIES` | `radarr,sonarr,radarr4k,sonarr4k` | Accepted categories. Add `stremio` if you use the addon |
| `AIRDCPP_WEB_URL` | — | Link from the Arr result to the folder in AirDC++ |

### Search and timing

| Variable | Default | Range | Use |
| --- | --- | --- | --- |
| `SEARCH_TIMEOUT` | `10` | 2–60 s | Wait per title variant. The wait starts when the search leaves the AirDC++ queue, not before |
| `DOWNLOAD_SEARCH_TIMEOUT` | `30` | s | Wait to find the source again when a download is started. Kept separate so searches stay fast |
| `RESPONSE_TIMEOUT` | `85` | 10–600 s | Maximum time to answer Radarr and Sonarr, which give up on each request after 100 s. Near the limit it stops opening file lists and trying variants; if it still runs over, it returns what it has and the search finishes in the background (and is cached) |
| `SEARCH_MAX_VARIANTS` | `4` | 1–20 | Title variants per search (localized, original, alternatives, `1x01`…) |
| `SEARCH_MIN_ACCEPTED_RESULTS` | `5` | 1–100 | Valid results after which no more variants are tried |
| `SEARCH_MAX_RESULTS` | `1000` | 1–5000 | AirDC++ results read |
| `AIRDCPP_MAX_ACTIVE_SEARCHES` | `1` | 1–8 | Simultaneous hub searches |
| `SEARCH_CACHE_TTL` | `300` | s | Cache for searches with results |
| `SEARCH_NEGATIVE_CACHE_TTL` | `30` | s | Cache for empty searches |
| `SEARCH_CACHE_SIZE` | `256` | | Cached searches |

### Seasons

| Variable | Default | Range | Use |
| --- | --- | --- | --- |
| `SEASON_INSPECT_MAX` | `10` | 0–200 | Ambiguous folders whose file list is opened to see which seasons they contain. `200` works well on large hubs |
| `SEASON_INSPECT_TIMEOUT` | `5` | 1–120 s | Time to open each file list. `60` works well on slow hubs |

### Per-series catalog

The first time something from a show is requested, after answering, the whole show is searched and its folders are opened. Every video is recorded with its season, episode, absolute number and language (including its folder's: `Monster - 01.mkv` inside `Monster [2004] [Cast++Jap+Subs]` is Spanish). Later requests for that show (Sonarr episode by episode, the addon) are answered from there without going to AirDC++ once the catalog has shown it misses nothing: until then the usual search runs as well and both are compared.

| Variable | Default | Range | Use |
| --- | --- | --- | --- |
| `CATALOG_ENABLED` | `true` | | Turns the catalog on |
| `CATALOG_TTL` | `3600` | 60–86400 s | How long a catalog lasts before it is rebuilt |
| `CATALOG_MAX_FOLDERS` | `60` | 1–300 | Maximum show folders opened |
| `CATALOG_BUILD_TIMEOUT` | `240` | 10–1800 s | Maximum time to go through the folders |
| `CATALOG_VERIFY_REQUESTS` | `3` | 0–50 | Consecutive requests in which the usual search adds nothing new before the catalog answers alone. Until then the usual search runs as well and both are compared, so nothing is lost |

### Other

| Variable | Default | Use |
| --- | --- | --- |
| `ALLOW_FILE_DELETE` | `false` | When Arr removes a download, also delete its files |
| `COMPLETED_RATIO` | `1.5` | Ratio reported to Arr when finished |
| `LOG_LEVEL` | `INFO` | Log level |
| `ALLOW_INSECURE` | `false` | Disables authentication. Testing only |

## Changes from the original

Each change is its own commit on top of `v2.0.0-beta.4`. To list them: `git log v2.0.0-beta.4..main`.

**Downloads**
- Finds the source again by **TTH**, so any user sharing the same file works. Keeps the destination folder for single files too.
- Movies that AirDC++ finds as a **folder** are downloaded as a folder. They used to fail with a 502 and Radarr downloaded them again.
- Separate download wait time (`DOWNLOAD_SEARCH_TIMEOUT`).

**Episode and season search**
- Also searches as `1x01` and accepts names with underscores (`Show_1x01`).
- Exact episode: `S01E01` no longer matches `S01E010`. Shows with a number after the title are discarded (`X-Men '97` when searching `X-Men`).
- Seasons inside subfolders (`Show/S2/…`) are inspected more and the name includes the subfolder. Episode 0 (`2x00` specials) is ignored when validating seasons.
- The wait counts from when the search leaves the **AirDC++ queue**, since AirDC++ enforces several seconds between searches.

**Anime and absolute numbering**
- Supports the Torznab `absolute` parameter. Sonarr in anime mode sends `q="Title 61"`, which is recognized too.
- Converts between season/episode and absolute number using **TVmaze** seasons, which match TVDB, Sonarr and Nuvio. Example: Dragon Ball GT 61 = S4 E14.
- Detects anime with TMDB (language `ja` + animation), tries the absolute number first and does not search Japanese titles.

**Language and title**
- A release is no longer tagged with the TMDB language just because it starts with the localized title, if that title is the same in other languages (e.g. *Dolls*), or if the name declares another language (German, Japanese, VOSTFR, ITA…).
- `Title (Alternative) (Year)` is sent as `Title (Year) (Alternative)` so Radarr and Sonarr can match the movie. Example: *Dolls (Marionetas) (2002)*.
- If the file name does not state the resolution, it is taken from the AirDC++ folder (`…/Show [4K]/ep.mkv`) and added as a Torznab attribute.
- Configurable TMDB language (`TMDB_LANGUAGE`).

**For the addon**
- `&partial=1` on Torznab returns what has been found so far without waiting for the search to finish.

## API

| Route | Use |
| --- | --- |
| `GET /torznab/api?t=caps` | Torznab capabilities |
| `GET /torznab/api?t=search\|movie\|tvsearch&apikey=…` | Search. Parameters: `q`, `imdbid`, `tmdbid`, `tvdbid`, `season`, `ep`, `absolute`, `cat`, `partial=1` |
| `GET /download/{id}.torrent` | Download link used by Arr |
| `GET /browse/{id}` | Redirects to the folder in AirDC++ (with `AIRDCPP_WEB_URL`) |
| `/api/v2/...` | Subset of the qBittorrent API |
| `GET /health/live`, `GET /health/ready` | Process alive / AirDC++ reachable |

The Arr indexer test, which carries no query, returns a validation result that cannot be downloaded.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Searches are slow | AirDC++ enforces several seconds between searches. Each variant waits up to `SEARCH_TIMEOUT` after leaving the queue |
| Found but the download fails | The source went offline. Raise `DOWNLOAD_SEARCH_TIMEOUT` or try another result |
| Full seasons are missing | Raise `SEASON_INSPECT_MAX` and `SEASON_INSPECT_TIMEOUT` |
| Sonarr: "AirDC++ server is currently unavailable… timed out" | The answer took over 100 s. Lower `RESPONSE_TIMEOUT`. If interactive search fails in the browser, raise the proxy timeout (e.g. `proxy_read_timeout 300s;` in Nginx Proxy Manager) |
| Other-language releases or Bluray discs are grabbed | The [custom formats](#profiles-and-custom-formats) or the Sonarr minimum score are missing |
| Radarr says "Unknown Movie" | The name lacks a title Radarr knows. Check the alternative titles in Radarr |
| Wrong language detected | Without `TMDB_API_KEY` the localized title and original language are unknown. Check `TMDB_LANGUAGE` |
| Downloads go to another client | The indexer is not linked to its download client in Arr |

## Development and releases

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
docker build -t airdcpp-torznab-bridge:local .
```

Workflow:

1. Changes are made on a branch (`dev`, `fix/...`). Each push publishes `:<branch>`, which is tested in a separate stack.
2. Once it works, it is merged into `main`.
3. To publish a release: **Actions → Imagen Docker → Run workflow**, branch `main`, with the version number.
   - **Stable** (`2.2.0`): GitHub release and `:2.2.0`, `:2.2`, `:stable` and `:latest`.
   - **Beta** (`2.2.0-rc.1`): GitHub pre-release and `:2.2.0-rc.1` and `:beta`. Does not touch `stable` or `latest`.

The workflow is [`.github/workflows/docker.yml`](.github/workflows/docker.yml) and uses the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets. [CodeQL](.github/workflows/codeql.yml) and [Trivy](.github/workflows/trivy.yml) scan the code and the image on every push and weekly.

Own versions following [SemVer](https://semver.org/): `2.1.0` is the original's `2.0.0-beta.4` plus this fork's changes.

To pull a new release from the original:

```bash
git remote add upstream https://github.com/Antaneyes/airdcpp-torznab-bridge.git
git fetch upstream --tags
git rebase <new-tag>
```

Files this fork removed (`launch_docker.bat`, `UPGRADING.md`, `docs/`) may show up as conflicts: resolve them by keeping them deleted.

Version history is in [CHANGELOG.md](CHANGELOG.md) (in Spanish).

## License

[GPL-3.0](LICENSE), the same as the original project by [Antaneyes](https://github.com/Antaneyes/airdcpp-torznab-bridge). This version is modified by Jesús Moruno (2026); the changes are described in [Changes from the original](#changes-from-the-original) and in the commit history. You may use, modify and redistribute it, as long as derived versions remain GPL-3.0 with their source available.

## Disclaimer

This software is provided **as is**, without warranty of any kind (see [LICENSE](LICENSE)). The author is not liable for any damage, loss or claim arising from its use.

- **It does not include, host or distribute any content.** It is a technical tool that only connects to the services each user configures in their own installation.
- **Each user is solely responsible** for how they use it and for complying with applicable law (including copyright) and the rules of the services and hubs they connect to. Use it only with content you have the right to download or play.
- **Not affiliated** with or endorsed by AirDC++, Stremio, Nuvio, Radarr, Sonarr, TMDB, TVmaze or any other project or brand mentioned. Names belong to their respective owners.

## Support

If you find it useful, you can buy me a coffee: [buymeacoffee.com/jmoruno](https://buymeacoffee.com/jmoruno) ☕
