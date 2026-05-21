# Changelog

Todos los cambios relevantes de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y este proyecto usa [SemVer](https://semver.org/lang/es/).

## [Unreleased]

## [1.0.0] - 2026-05-21

Primer release público. Incluye todo el estado actual del proyecto.

### Added
- **Multi-user**: descubrimiento automático de listas públicas para cualquier username de Letterboxd añadido.
- **Custom Lists** con sources (watchlists y listas), operador unión / intersección, subtract, exclude already-watched, filtros estáticos (rating, año) y rotación temporal con batch size configurable.
- **UI web** React 18 SPA sin build step (Babel-standalone): Dashboard, Users, User detail, Lists global, Custom Lists con editor (preview en vivo) y Activity con polling 2s y filtros por nivel.
- **Endpoints Radarr**: `/lists/<slug>/`, `/<username>/watchlist/`, `/<username>/<list-slug>/`. Formato JSON array `{tmdb_id, title?, imdb_id?, poster_url?, genres?}` con soporte `ETag` / `If-None-Match`.
- **Anti-flap**: umbral de confirmación antes de borrar un item (default 3 scrapes; sobrescribible por lista desde la UI).
- **Scheduling** con APScheduler en proceso: incremental + full scrape por watchlist y por lista, poll RSS, films backstop, discovery, rotation tick.
- **Imagen Docker** `maxlainz/watchlistarr` multi-arch (`linux/amd64`, `linux/arm64`), un único proceso uvicorn, persistencia SQLite en `/data` con migraciones Alembic automáticas al arranque.
- **Sistema de versiones**: SemVer + Conventional Commits, doble bump (`pyproject.toml` + `__init__.py`), tags `vX.Y.Z` desde `main`, publicación automática en Docker Hub con tags `:X.Y.Z`, `:X.Y`, `:latest`, `:sha-<short>`. Reglas y procedimiento en [`.claude/versioning.md`](.claude/versioning.md).
- **README** público en inglés con quick start, conexión a Radarr, configuración, backup, troubleshooting y aviso sobre la duración del primer scrape.
- **Docs internos** en `.claude/` cubriendo arquitectura, reglas, scraping de Letterboxd (listas y RSS), contrato Radarr, modelo de datos, sync strategy, UI features, tech stack y workflows.
