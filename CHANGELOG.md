# Changelog

Todos los cambios relevantes de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y este proyecto usa [SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Custom lists: pueden usar otras custom lists como source (`include` o
  `subtract`). Semántica: A ve lo que B sirve a Radarr ahora (
  `custom_list_items` materializados), respetando `max_items`, `sort_order`,
  `snapshot_interval` y rotación de B. Coherencia eventual — A recompone en
  su propia tick (edición, rotation, snapshot). Validación server-side de
  ciclos con BFS antes de guardar. El editor muestra una nueva sección
  "Custom lists" en el SourcePicker.

### Changed
- `custom_list_sources` migra a un esquema polimórfico: nuevo PK surrogate
  `id` y columna nullable `source_custom_list_id` (FK a `custom_lists`).
  Exactamente una de `list_id` / `source_custom_list_id` debe estar set
  (CHECK constraint). Migración 0009. Los datos existentes (todos con
  `list_id` set) se preservan.

## [1.2.2] - 2026-05-22

### Fixed
- Custom lists: al editar una lista y reducir `max_items`, el recálculo no
  truncaba los items sobrantes — la lista seguía sirviendo el tamaño anterior
  a Radarr. `recalculate()` ahora elimina el excedente eligiendo qué
  conservar según el `sort_order` configurado (top-N por rating en
  `RATING_DESC`, top-N por posición en `LETTERBOXD`/`REVERSE`, aleatorio en
  `RANDOM`). Como defensa en profundidad, `serialize_custom_list` aplica
  `LIMIT max_items` al servir.

## [1.2.1] - 2026-05-22

### Fixed
- `rotation_tick` lanzaba `TypeError: can't compare offset-naive and
  offset-aware datetimes` cada hora. SQLite descarta la tzinfo en
  columnas `DateTime` sin `timezone=True`, así que `last_rotated_at`
  vuelve naive al releer desde la DB y la suma con `utcnow()` (aware)
  rompía. `rotate()` ahora normaliza el valor a UTC-aware antes de la
  aritmética, siguiendo el mismo patrón que `_iso()` en la API. Test de
  regresión que fuerza el round-trip por DB.

## [1.2.0] - 2026-05-21

### Added
- Custom lists: filtros relativos a hoy. `year_last_n` selecciona pelis
  estrenadas en los últimos N años (`current_year - N + 1 .. current_year`)
  y `added_last_n_days` filtra por fecha de adición a la lista de origen.
  Se evalúan en cada servido a Radarr, así que la ventana se mueve sola.
- Custom lists: nuevo `SortOrder.RATING_DESC` que ordena por la
  valoración media en Letterboxd (descendente). Requiere ratings en DB;
  el scraper de `film_page` ahora extrae el rating y hay un job
  `rating_backfill` + script `scripts/backfill_ratings.py` para poblar
  histórico.
- Migración Alembic `0005_custom_lists_relative_filters` con las nuevas
  columnas y el enum extendido.
- Test de integración `tests/integration/test_rotation.py` que cubre
  rotación con los nuevos sorts y filtros relativos.

### Fixed
- `SortOrder.LETTERBOXD`, `REVERSE` y `RANDOM` se ignoraban en la
  selección final de items servida a Radarr (siempre caía a orden por
  defecto). Ahora se respetan los tres modos.

### Changed
- Filtro de año en custom lists: se documenta que `year_from`/`year_to`
  son absolutos y los nuevos `*_last_n` son relativos a hoy.
- `scripts/smoke.py` cubre los nuevos filtros y el sort por rating.

## [1.1.0] - 2026-05-21

### Added
- Compatibilidad con el provider **Custom Lists** de Radarr además de
  **StevenLu Custom**. Cada item del JSON Radarr incluye ahora `id`
  (= `tmdb_id`) junto a `tmdb_id`, `title` e `imdb_id`. Newtonsoft.Json
  del lado de Radarr ignora campos extra, así que el mismo endpoint
  funciona contra los dos provider; el usuario elige cuál usar en la
  UI de Radarr. Custom Lists resuelve por TMDB ID directo, sin
  depender del scrape de `imdb_id` desde la film page.
- `scripts/smoke.py` asserta que `id == tmdb_id` tanto en listas
  de usuario como en custom lists multi-source.

### Changed
- `.claude/radarr-custom-list.md` reescrita: documenta los dos
  parsers de Radarr (`RadarrListParser` y `StevenLuParser`) en
  paralelo, con un único ejemplo JSON compatible con ambos.
- README sección "Connecting Radarr" menciona ambas opciones.

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
