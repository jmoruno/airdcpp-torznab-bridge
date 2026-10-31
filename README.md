# AirDC++ Torznab Bridge

[![Build](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/docker.yml) [![CodeQL](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/codeql.yml) [![Trivy](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/trivy.yml/badge.svg?branch=main)](https://github.com/jmoruno/airdcpp-torznab-bridge/actions/workflows/trivy.yml) [![Release](https://img.shields.io/github/v/release/jmoruno/airdcpp-torznab-bridge)](https://github.com/jmoruno/airdcpp-torznab-bridge/releases/latest) [![Docker pulls](https://img.shields.io/docker/pulls/jmorunofdz/airdcpp-torznab-bridge)](https://hub.docker.com/r/jmorunofdz/airdcpp-torznab-bridge) [![Image size](https://img.shields.io/docker/image-size/jmorunofdz/airdcpp-torznab-bridge/stable)](https://hub.docker.com/r/jmorunofdz/airdcpp-torznab-bridge) [![License](https://img.shields.io/github/license/jmoruno/airdcpp-torznab-bridge)](LICENSE)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/jmoruno)

**Español** · [English](README.en.md)

Puente entre **Radarr / Sonarr** y los hubs de **AirDC++**:

- **Indexador Torznab**: Radarr y Sonarr buscan en los hubs como si fuera un tracker.
- **Cliente de descarga compatible con qBittorrent**: lanzan la descarga en AirDC++ y siguen su progreso.

Es una versión propia de [Antaneyes/airdcpp-torznab-bridge](https://github.com/Antaneyes/airdcpp-torznab-bridge), basada en su `v2.0.0-beta.4`, con arreglos para hubs españoles, anime y el addon [airdcpp-stream](https://github.com/jmoruno/airdcpp-stream). Licencia [GPL-3.0](LICENSE), igual que el original.

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
- [Licencia](#licencia)
- [Aviso legal](#aviso-legal)

## Imagen Docker

| Etiqueta | Canal | Para qué |
| --- | --- | --- |
| `stable` / `latest` | estable | Producción: última versión estable |
| `X.Y` / `X.Y.Z` (p. ej. `2.1.0`) | estable | Fijar una versión concreta o volver atrás |
| `beta` / `X.Y.Z-rc.N` | beta | Versiones candidatas, antes de pasar a estable |
| `dev` y otras ramas | desarrollo | Probar cambios sin tocar producción |
| `sha-<commit>` | — | Una build exacta |

Imagen: `jmorunofdz/airdcpp-torznab-bridge` (`linux/amd64`).

## Despliegue en Unraid / Portainer

Se usan **dos contenedores con la misma imagen**: uno para películas y otro para series. Así cada uno guarda en su carpeta y tiene su propia caché.

| Contenedor | Puerto | Carpeta (`SAVE_PATH`) | Categorías |
| --- | --- | --- | --- |
| `airdcpp-bridge-movies` | 8001 | `/Downloads` | `radarr,radarr4k,stremio` |
| `airdcpp-bridge-series` | 8002 | `/DownloadsSeries` | `sonarr,sonarr4k,stremio` |

1. Crea un stack con [`docker-compose.yml`](docker-compose.yml).
2. En las variables del stack, carga un `.env` con los valores de [`.env.example`](.env.example): contraseñas, claves y URLs.
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

### Perfiles y formatos personalizados en español

Sin esto, Radarr y Sonarr cogen versiones en otros idiomas o discos Bluray completos (carpetas `BDMV`, `.iso`), que no se pueden reproducir ni importar bien. Los formatos están listos para importar en [`arr/`](arr): en Radarr o Sonarr, **Ajustes → Formatos personalizados → +** → **Importar** y pega el JSON.

**Radarr** (el perfil sí tiene idioma):

| Ajuste | Valor |
| --- | --- |
| Perfil → Idioma | **Spanish** |
| Formato [`Bluray`](arr/radarr/bluray.json) | **−10000**: bloquea solo discos (`bdmv`, `m2ts`, `iso`, `bd25/50/66/100`, `full disc`, `complete`). Remux y rips (`BDRip`, `BluRay x264`) sí pasan |
| Puntuación mínima | `0` |

**Sonarr** (v4 no tiene idioma en el perfil, todo va con formatos):

| Formato | Puntuación | Qué detecta |
| --- | --- | --- |
| [`Español (idioma)`](arr/sonarr/espanol-idioma.json) | **+100** | Idioma detectado Spanish (el bridge lo envía) |
| [`Español (título)`](arr/sonarr/espanol-titulo.json) | **+100** | El nombre dice `castellano`, `spanish`, `español`, `dual`, `multi`, `temporada`, `cap`… |
| [`Bluray`](arr/sonarr/bluray.json) | **−10000** | Discos. A diferencia de Radarr usa `complete.?blu.?ray` en vez de `complete`, porque en series "COMPLETE" también marca packs de temporada normales |
| **Puntuación mínima del perfil** | **100** | Sin algo en español, se rechaza |

> Copia las expresiones del JSON tal cual: un espacio al principio (`"   \b(…"`) hace que no coincidan nunca y no da ningún error.

Para hubs en inglés: pon el idioma del perfil de Radarr en **English**, en Sonarr cambia `Español (idioma)` por el idioma que quieras (o quítalo junto con la puntuación mínima) y usa `TMDB_LANGUAGE=en-US` en el bridge.

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
| `TMDB_LANGUAGE` | `es-ES` | Idioma de los títulos de TMDB y el que se deduce cuando el nombre empieza por ese título (`en-US`, `fr-FR`…) |
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
- Idioma de TMDB configurable (`TMDB_LANGUAGE`).

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
| Se descargan versiones en otro idioma o discos Bluray | Faltan los [formatos personalizados](#perfiles-y-formatos-personalizados-en-español) o la puntuación mínima en Sonarr |
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
3. Para publicar una versión: **Actions → Imagen Docker → Run workflow**, rama `main`, con el número de versión.
   - **Estable** (`2.2.0`): release en GitHub y `:2.2.0`, `:2.2`, `:stable` y `:latest`.
   - **Beta** (`2.2.0-rc.1`): pre-release en GitHub y `:2.2.0-rc.1` y `:beta`. No toca `stable` ni `latest`.

El workflow es [`.github/workflows/docker.yml`](.github/workflows/docker.yml) y usa los secretos `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN`.

Versiones propias con [SemVer](https://semver.org/lang/es/): la `2.1.0` es la `2.0.0-beta.4` del original más los cambios de esta versión.

- Para traer una versión nueva del original:

```bash
git remote add upstream https://github.com/Antaneyes/airdcpp-torznab-bridge.git
git fetch upstream --tags
git rebase <nueva-etiqueta>
```

Al traer cambios del original, los ficheros que esta versión ha quitado (`launch_docker.bat`, `UPGRADING.md`, `docs/`) pueden salir como conflicto: se resuelven dejándolos borrados.

El historial de versiones está en [CHANGELOG.md](CHANGELOG.md).

## Licencia

[GPL-3.0](LICENSE), la misma que el proyecto original de [Antaneyes](https://github.com/Antaneyes/airdcpp-torznab-bridge). Esta versión está modificada por Jesús Moruno (2026); los cambios están descritos en [Cambios respecto al original](#cambios-respecto-al-original) y en el historial de commits. Puedes usarla, modificarla y redistribuirla, siempre que las versiones derivadas sigan siendo GPL-3.0 y con el código disponible.

## Aviso legal

Este software se ofrece **tal cual**, sin garantías de ningún tipo (ver [LICENSE](LICENSE)). El autor no se hace responsable de ningún daño, pérdida ni reclamación derivados de su uso.

- **No incluye, aloja ni distribuye contenido.** Es una herramienta técnica que solo se conecta a los servicios que configura cada usuario en su propia instalación.
- **Cada usuario es el único responsable** de cómo lo usa y de cumplir la legislación aplicable (incluida la de propiedad intelectual) y las normas de los servicios y hubs a los que se conecta. Úsalo solo con contenido que tengas derecho a descargar o reproducir.
- **No está afiliado** a AirDC++, Stremio, Nuvio, Radarr, Sonarr, TMDB, TVmaze ni a ningún otro proyecto o marca mencionado, ni cuenta con su respaldo. Los nombres pertenecen a sus respectivos titulares.

*This software is provided "as is", without warranty of any kind. It does not include, host or distribute any content. Users are solely responsible for how they use it and for complying with applicable laws and the terms of the services they connect to. Not affiliated with or endorsed by any of the projects mentioned.*

## Apoyar el proyecto

Si te resulta útil, puedes invitarme a un café: [buymeacoffee.com/jmoruno](https://buymeacoffee.com/jmoruno) ☕
