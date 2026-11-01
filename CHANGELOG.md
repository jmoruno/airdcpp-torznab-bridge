# Registro de cambios

Versiones con [SemVer](https://semver.org/lang/es/). Las notas de cada versión también están en las [releases](../../releases).

Los cambios del proyecto original hasta la `2.0.0-beta.4` están en el [CHANGELOG de Antaneyes](https://github.com/Antaneyes/airdcpp-torznab-bridge/blob/v2.0.0-beta.4/CHANGELOG.md).

## [2.2.1] - 2026-11-01

### Corregido

- Las búsquedas de temporada con muchas carpetas dudosas (títulos genéricos como "Monster") podían tardar más de 100 s, y Sonarr descartaba todos los resultados de AirDC++. Ahora la respuesta llega antes de `RESPONSE_TIMEOUT` (85 s por defecto): deja de abrir listas y de probar variantes al acercarse el límite y, si aun así se pasa, devuelve lo encontrado y termina la búsqueda en segundo plano.

## [2.2.0] - 2026-10-31

### Añadido

- `TMDB_LANGUAGE`: idioma de los títulos de TMDB (`es-ES` por defecto, `en-US`, `fr-FR`…). El idioma que se deduce por el título sigue a esta variable.
- README en inglés.
- Análisis de seguridad con CodeQL y Trivy en cada push y cada semana.

### Corregido

- Los errores de AirDC++ ya no se devuelven tal cual en las respuestas HTTP; se registran en el log.
- Los identificadores que llegan a `torrents/add` se validan antes de usarlos o registrarlos.
- La detección de anime (`"Título 61"`) ya no usa una expresión regular que podía ser lenta con textos manipulados.

## [2.1.1] - 2026-10-31

### Corregido

- `/health` y la API muestran la versión real en lugar de `2.0.0-beta.4`.

### Cambiado

- Quitados ficheros del original que no aplican a esta versión (`launch_docker.bat`, `UPGRADING.md`, `docs/`). `docker-compose.yml` y `.env.example` son los de esta versión.

## [2.1.0] - 2026-10-31

Primera versión propia, basada en la `2.0.0-beta.4` de Antaneyes.

### Añadido

- Numeración absoluta (parámetro Torznab `absolute` y `q="Título 61"` de Sonarr en modo anime), con las temporadas de TVmaze.
- Detección de anime con TMDB: prueba primero el número absoluto y no busca títulos en japonés.
- Resultados parciales con `&partial=1`, para el addon airdcpp-stream.
- Resolución tomada de la carpeta de AirDC++ cuando el nombre del fichero no la indica.
- `DOWNLOAD_SEARCH_TIMEOUT`: espera aparte para volver a encontrar la fuente al descargar.
- Imagen en Docker Hub (`jmorunofdz/airdcpp-torznab-bridge`) con canales `stable`, `beta` y `dev`.

### Corregido

- Descargas: vuelve a encontrar la fuente por TTH y respeta la carpeta de destino en ficheros sueltos.
- Las películas que AirDC++ encuentra como carpeta se descargan como carpeta, en vez de fallar con un 502.
- La espera de cada búsqueda cuenta desde que sale de la cola de AirDC++.
- Capítulos: también como `1x01`, con nombres que llevan guiones bajos, coincidencia exacta (`S01E01` ≠ `S01E010`) y sin series con número detrás del título.
- Temporadas en subcarpetas: más inspección y el nombre incluye la subcarpeta. Ignora el capítulo 0 al validar.
- Idioma: ya no marca como "Spanish" por el título cuando ese título es igual en otros idiomas, ni cuando el nombre declara otro idioma.
- `Título (Alternativo) (Año)` se envía como `Título (Año) (Alternativo)` para que Radarr y Sonarr lo emparejen.
