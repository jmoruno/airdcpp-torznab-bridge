# Seguridad

## Versiones con soporte

Solo la última versión estable (canal `stable`).

## Despliegue

- No expongas el bridge ni el AirDC++ Web Client directamente a Internet.
- Deja `ALLOW_INSECURE=false` y usa contraseñas y claves largas y distintas para el bridge y para AirDC++.
- Limita el acceso por firewall o red de Docker a los equipos de Radarr y Sonarr que lo necesitan.
- Deja `ALLOW_FILE_DELETE=false` salvo que necesites que Arr borre ficheros.
- Trata las URLs Torznab como secretas: pueden llevar la API key.

Los endpoints de salud (`/health/*`) no piden autenticación. Solo muestran el estado, la versión y el número de hashes conocidos.

## Avisar de una vulnerabilidad

Usa el aviso privado de vulnerabilidades de GitHub en este repositorio. No abras una incidencia pública con credenciales, direcciones de hubs, enlaces a listas de ficheros ni detalles del fallo.
