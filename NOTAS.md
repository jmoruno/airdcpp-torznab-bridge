# Notas de esta copia (jmoruno)

Copia privada de [Antaneyes/airdcpp-torznab-bridge](https://github.com/Antaneyes/airdcpp-torznab-bridge)
a partir de `v2.0.0-beta.4`, con nuestros arreglos encima (un commit por arreglo: `git log v2.0.0-beta.4..`).

## Desplegar en Unraid (Portainer)

- Stack con `docker-compose.unraid.yml` (imagen `jmorunofdz/airdcpp-torznab-bridge:latest`, la publica GitHub Actions en cada push a `main`).
- Variables del stack: las de `unraid.env.example` (secretos, URLs del bridge y de AirDC++).
- Monta dos contenedores con la misma imagen: `airdcpp-bridge-movies` (8001) y `airdcpp-bridge-series` (8002).

## Traer versiones nuevas del original

```bash
git remote add upstream https://github.com/Antaneyes/airdcpp-torznab-bridge.git
git fetch upstream --tags
git rebase <nueva-etiqueta>   # o git merge
```
