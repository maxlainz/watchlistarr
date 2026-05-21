# Changelog

Todos los cambios relevantes de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y este proyecto usa [SemVer](https://semver.org/lang/es/).

## [Unreleased]

## [1.0.2] - 2026-05-21

### Fixed
- `sqlite3.OperationalError: database is locked` en jobs solapados del scheduler.
  Los scrapers mantenían una transacción de escritura abierta durante los fetches
  HTTP a Letterboxd; con WAL solo hay un writer a la vez y el `busy_timeout=10s`
  saltaba cuando dos jobs (p.ej. RSS + watchlist-full) intentaban escribir en
  paralelo.

### Changed
- Refactor profundo de los scrapers a un patrón **fetch-first / write-last**: HTTP
  y lecturas fuera de toda transacción, sesiones cortas solo para los upserts.
  Afecta a `rss_watcher`, `films_backstop`, `watchlist`, `lists` y `discovery`.
- `resolve_film` se sustituye por `resolve_films` (batch) que devuelve dataclasses
  planas `ResolvedFilm`, seguras de cruzar boundaries de sesión.
- `with_scrape_audit` envuelve una corrutina (en vez de inyectar sesión al body);
  los scrapers gestionan sus propias mini-sesiones internamente.
- `scheduler._with_user` / `_with_list` y `onboarding._initial_run` se adaptan a
  la nueva firma `(factory, client, ...)`.

### Added
- Test de regresión `tests/integration/test_scrape_concurrency.py` que lanza
  `poll_rss_for_user` y `backstop_films_for_user` en paralelo con `asyncio.gather`
  para confirmar que no se reproduce el lock.

## [1.0.1] - 2026-05-21

### Fixed
- Endpoint Radarr ahora incluye `imdb_id` por película. El parser de Radarr
  para "Custom List" (`StevenLuParser.cs`) solo lee `title` e `imdb_id`;
  servir únicamente `tmdb_id` causaba "No results were returned from your
  import list" en cuanto Radarr intentaba sincronizar.

### Added
- Columna `films.imdb_id` (migración Alembic `0004_films_imdb_id`, índice unique parcial).
- `parse_film_page` extrae el IMDb ID del HTML de Letterboxd (link `imdb.com/title/tt…`).
- `resolve_film` re-resuelve lazy un film cacheado cuando su `imdb_id` está en `NULL`.
- Script `scripts/backfill_imdb.py` y módulo `services/scrape/imdb_backfill.py` para enriquecer en bloque los films ya en DB.

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
