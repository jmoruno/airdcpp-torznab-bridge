# AirDC++ Torznab Bridge (jmoruno)

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-jmoruno-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/jmoruno)

Puente entre **Radarr / Sonarr** y los hubs de **AirDC++**:

- **Indexador Torznab**: Radarr y Sonarr buscan en los hubs como si fuera un tracker.
- **Cliente de descarga compatible con qBittorrent**: lanzan la descarga en AirDC++ y siguen su progreso.

Es una versión propia de [Antaneyes/airdcpp-torznab-bridge](https://github.com/Antaneyes/airdcpp-torznab-bridge) `v2.0.0-beta.4` con arreglos para hubs españoles, anime y el addon [airdcpp-stream](https://github.com/jmoruno/airdcpp-stream). Licencia [GPL-3.0](LICENSE), igual que el original.

> Úsalo solo dentro de tu red. No lo expongas directamente a Internet.

## Índice

- [Imagen Docker](#imagen-docker)
- [Despliegue en Unraid / Portainer](#despliegue-en-unraid--portainer)
- [Configurar Radarr y Sonarr](#configurar-radarr-y-sonarr)
- [Variables de entorno](#variables-de-entorno)
- [Cambios respecto al original](#cambios-respecto-al-original)
- [API](#api)
- [Problemas frecuentes](#problemas-frecuentes)
- [Desarrollo y publicación](#desarrollo-y-publicación)

## Imagen Docker

| Etiqueta | Cuándo se publica | Para qué |
| --- | --- | --- |
| `latest` | Al publicar una versión | Producción |
| `X.Y.Z` (p. ej. `2.0.0-beta.4-jm.1`) | Al publicar una versión | Fijar una versión concreta o volver atrás |
| `<rama>` (p. ej. `dev`, `main`) | En cada push a esa rama | Probar cambios sin tocar producción |
| `sha-<commit>` | En cada build | Una build exacta |

Imagen: `jmorunofdz/airdcpp-torznab-bridge` (`linux/amd64`).

## Despliegue en Unraid / Portainer

Se usan **dos contenedores con la misma imagen**: uno para películas y otro para series. Así cada uno guarda en su carpeta y tiene su propia caché.

| Contenedor | Puerto | Carpeta (`SAVE_PATH`) | Categorías |
| --- | --- | --- | --- |
| `airdcpp-bridge-movies` | 8001 | `/Downloads` | `radarr,radarr4k,stremio` |
| `airdcpp-bridge-series` | 8002 | `/DownloadsSeries` | `sonarr,sonarr4k,stremio` |

1. Crea un stack con [`docker-compose.unraid.yml`](docker-compose.unraid.yml).
2. En las variables del stack, carga un `.env` con los valores de [`unraid.env.example`](unraid.env.example): contraseñas, claves y URLs.
3. Despliega y comprueba que funciona:

```bash
curl http://IP-DEL-SERVIDOR:8001/health/ready
curl http://IP-DEL-SERVIDOR:8002/health/ready
```

**Actualizar:** cuando haya versión nueva, en Portainer *Update the stack* con *Re-pull image*.

**Probar una rama:** crea otro stack con la imagen `:dev` (u otra rama), otros puertos (p. ej. 8011/8012) y otros nombres de contenedor y volumen, para no tocar producción.

**Datos:** cada contenedor guarda su base de datos SQLite en un volumen (`bridge-data`, `bridge-series-data`). Si cambias el nombre del stack, Docker crea volúmenes nuevos y se pierde la caché y el seguimiento de las descargas en curso.

**Rutas:** `SAVE_PATH` es la carpeta **tal como la ve AirDC++**, no como la ve el bridge. El bridge no necesita montar las descargas.

## Configurar Radarr y Sonarr

### Indexador (Torznab)

| Campo | Radarr | Sonarr |
| --- | --- | --- |
| URL | `http://IP:8001/torznab` | `http://IP:8002/torznab` |
| API Path | `/api` | `/api` |
| API Key | `BRIDGE_API_KEY` | `BRIDGE_API_KEY` |
| Categorías | `2000`, `2040` | `5000`, `5040` |
| RSS | desactivado (los hubs no tienen RSS) | desactivado |
| Cliente de descarga | el de este bridge | el de este bridge |

Asocia el indexador a su cliente en *Opciones avanzadas → Cliente de descarga*. Si no, Radarr o Sonarr pueden mandar lo que encuentra el bridge a otro cliente torrent.

### Cliente de descarga (qBittorrent)

| Campo | Valor |
| --- | --- |
| Host / Puerto | IP del servidor y `8001` (Radarr) o `8002` (Sonarr) |
| Usuario / Contraseña | `BRIDGE_USERNAME` / `BRIDGE_PASSWORD` |
| Categoría | `radarr` / `sonarr` (tiene que estar en `DOWNLOAD_CATEGORIES`) |
| Descarga secuencial, primera y última pieza | desactivado |

Si Radarr o Sonarr ven la carpeta de descargas con otra ruta que AirDC++, añade un *Remote Path Mapping*:

- **Host:** el mismo que pusiste en el cliente.
- **Remote:** `SAVE_PATH`.
- **Local:** la ruta montada en Radarr o Sonarr.

## Variables de entorno

### Obligatorias

| Variable | Para qué |
| --- | --- |
| `AIRDCPP_URL` | API web de AirDC++, p. ej. `http://host.docker.internal:54345` |
| `AIRDCPP_USER`, `AIRDCPP_PASS` | Usuario de AirDC++. Necesita permisos para hubs, búsqueda, listas de ficheros y cola |
| `BRIDGE_API_KEY` | Clave del indexador Torznab |
| `BRIDGE_USERNAME`, `BRIDGE_PASSWORD` | Login del cliente qBittorrent |
| `PUBLIC_URL` | URL con la que Radarr y Sonarr llegan a este contenedor (los enlaces de descarga la usan) |
| `SAVE_PATH` | Carpeta de destino tal como la ve AirDC++ |

### Recomendadas

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `TMDB_API_KEY` | — | Títulos en español y alternativos, idioma original y detección de anime. Sin ella se busca solo por el título que manda Arr |
| `DOWNLOAD_CATEGORIES` | `radarr,sonarr,radarr4k,sonarr4k` | Categorías aceptadas. Añade `stremio` si usas el addon |
| `AIRDCPP_WEB_URL` | — | Enlace desde el resultado en Arr a la carpeta en AirDC++ |

### Búsqueda y tiempos

| Variable | Por defecto | Rango | Para qué |
| --- | --- | --- | --- |
| `SEARCH_TIMEOUT` | `10` | 2–60 s | Espera por cada variante de título. La espera empieza cuando la búsqueda sale de la cola de AirDC++, no antes |
| `DOWNLOAD_SEARCH_TIMEOUT` | `30` | s | Espera para volver a encontrar la fuente al pulsar descargar. Va aparte para que las búsquedas sigan siendo rápidas |
| `SEARCH_MAX_VARIANTS` | `4` | 1–20 | Variantes de título por búsqueda (español, original, alternativos, `1x01`…) |
| `SEARCH_MIN_ACCEPTED_RESULTS` | `5` | 1–100 | Resultados válidos con los que deja de probar variantes |
| `SEARCH_MAX_RESULTS` | `1000` | 1–5000 | Resultados de AirDC++ que se leen |
| `AIRDCPP_MAX_ACTIVE_SEARCHES` | `1` | 1–8 | Búsquedas simultáneas en los hubs |
| `SEARCH_CACHE_TTL` | `300` | s | Caché de búsquedas con resultados |
| `SEARCH_NEGATIVE_CACHE_TTL` | `30` | s | Caché de búsquedas vacías |
| `SEARCH_CACHE_SIZE` | `256` | | Búsquedas guardadas en caché |

### Temporadas

| Variable | Por defecto | Rango | Para qué |
| --- | --- | --- | --- |
| `SEASON_INSPECT_MAX` | `10` | 0–200 | Carpetas dudosas cuya lista de ficheros se abre para ver qué temporadas tienen. En hubs grandes conviene `200` |
| `SEASON_INSPECT_TIMEOUT` | `5` | 1–120 s | Tiempo para abrir cada lista de ficheros. En hubs lentos conviene `60` |

### Otras

| Variable | Por defecto | Para qué |
| --- | --- | --- |
| `ALLOW_FILE_DELETE` | `false` | Si Arr pide borrar una descarga, borra también los ficheros |
| `COMPLETED_RATIO` | `1.5` | Ratio que se informa a Arr al terminar |
| `LOG_LEVEL` | `INFO` | Nivel de log |
| `ALLOW_INSECURE` | `false` | Quita la autenticación. Solo para pruebas |

## Cambios respecto al original

Cada cambio es un commit propio sobre `v2.0.0-beta.4`. Para verlos: `git log v2.0.0-beta.4..main`.

**Descargas**
- Vuelve a encontrar la fuente por **TTH**, de modo que vale cualquier usuario que tenga el mismo fichero. Respeta la carpeta de destino también en ficheros sueltos.
- Las películas que AirDC++ encuentra como **carpeta** se descargan como carpeta. Antes fallaban con un 502 y Radarr volvía a descargarlas.
- Tiempo de espera de descarga separado del de búsqueda (`DOWNLOAD_SEARCH_TIMEOUT`).

**Búsqueda de capítulos y temporadas**
- Busca también como `1x01` y acepta nombres con guiones bajos (`Serie_1x01`).
- Capítulo exacto: `S01E01` ya no coincide con `S01E010`. Descarta series con un número detrás del título (`X-Men '97` al buscar `X-Men`).
- Las temporadas dentro de subcarpetas (`Serie/T.2/…`) se inspeccionan más y el nombre incluye la subcarpeta. Ignora el capítulo 0 (especiales `2x00`) al validar temporadas.
- La espera cuenta desde que la búsqueda sale de la **cola de AirDC++**, porque AirDC++ obliga a dejar varios segundos entre búsquedas.

**Anime y numeración absoluta**
- Admite el parámetro Torznab `absolute`. Sonarr en modo anime manda `q="Título 61"`, que también se reconoce.
- Convierte entre temporada/capítulo y número absoluto con las temporadas de **TVmaze**, que usan la misma numeración que TVDB, Sonarr y Nuvio. Ejemplo: Dragon Ball GT 61 = T4 E14.
- Detecta anime con TMDB (idioma `ja` + animación), prueba primero el número absoluto y no busca títulos en japonés.

**Idioma y título**
- Ya no marca una versión como "Spanish" solo porque empieza por el título en español, si ese título es igual en otros idiomas (por ejemplo *Dolls*). Tampoco lo hace si el nombre declara otro idioma (German, Japanese, VOSTFR, ITA…).
- `Título (Alternativo) (Año)` se envía como `Título (Año) (Alternativo)` para que Radarr y Sonarr lo emparejen con la película. Ejemplo: *Dolls (Marionetas) (2002)*.
- Si el nombre del fichero no dice la resolución, la toma de la carpeta de AirDC++ (`…/Serie [4K]/cap.mkv`) y la añade como atributo Torznab.

**Para el addon**
- `&partial=1` en Torznab devuelve lo encontrado hasta el momento sin esperar a que termine la búsqueda.

## API

| Ruta | Para qué |
| --- | --- |
| `GET /torznab/api?t=caps` | Capacidades Torznab |
| `GET /torznab/api?t=search\|movie\|tvsearch&apikey=…` | Búsqueda. Parámetros: `q`, `imdbid`, `tmdbid`, `tvdbid`, `season`, `ep`, `absolute`, `cat`, `partial=1` |
| `GET /download/{id}.torrent` | Enlace de descarga que usa Arr |
| `GET /browse/{id}` | Redirige a la carpeta en AirDC++ (con `AIRDCPP_WEB_URL`) |
| `/api/v2/...` | Subconjunto de la API de qBittorrent |
| `GET /health/live`, `GET /health/ready` | Proceso vivo / AirDC++ accesible |

El test del indexador en Arr, que no lleva búsqueda, devuelve un resultado de validación que no se puede descargar.

## Problemas frecuentes

| Síntoma | Causa probable |
| --- | --- |
| Las búsquedas tardan mucho | AirDC++ deja varios segundos entre búsquedas. Cada variante espera hasta `SEARCH_TIMEOUT` desde que sale de la cola |
| Encuentra pero falla al descargar | La fuente se desconectó. Sube `DOWNLOAD_SEARCH_TIMEOUT` o prueba con otro resultado |
| Faltan temporadas completas | Sube `SEASON_INSPECT_MAX` y `SEASON_INSPECT_TIMEOUT` |
| Radarr dice "Unknown Movie" | El nombre no lleva el título que conoce Radarr. Revisa los títulos alternativos en Radarr |
| Idioma mal detectado | Sin `TMDB_API_KEY` no se conocen el título español ni el idioma original |
| Lo descargado va a otro cliente | El indexador no está asociado a su cliente de descarga en Arr |

## Desarrollo y publicación

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
docker build -t airdcpp-torznab-bridge:local .
```

Flujo de trabajo:

1. Los cambios se hacen en una rama (`dev`, `fix/...`). Cada push publica `:<rama>`, que se prueba en un stack aparte.
2. Cuando funciona, se fusiona en `main`.
3. Para publicar una versión: **Actions → Imagen Docker → Run workflow**, rama `main`, con el número de versión (p. ej. `2.0.0-beta.4-jm.2`). Crea la etiqueta `vX.Y.Z` y la release en GitHub con las notas de cambios, y publica `:X.Y.Z` y `:latest`.

El workflow es [`.github/workflows/docker.yml`](.github/workflows/docker.yml) y usa los secretos `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN`.

Versiones: `2.0.0-beta.4-jm.N`, es decir, la versión del original de la que parte más un número propio.

- Para traer una versión nueva del original:

```bash
git remote add upstream https://github.com/Antaneyes/airdcpp-torznab-bridge.git
git fetch upstream --tags
git rebase <nueva-etiqueta>
```

`UPGRADING.md`, `CHANGELOG.md` y `docs/` son la documentación del original y se mantienen tal cual para facilitar las actualizaciones.

## Apoyar el proyecto

Si te resulta útil, puedes invitarme a un café: [buymeacoffee.com/jmoruno](https://buymeacoffee.com/jmoruno) ☕
