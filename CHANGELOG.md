# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [SemVer](https://semver.org/).

## [Unreleased]

### Changed
- License changed from MIT to GPL-3.0-or-later.
- README: license badge, "How it works" overview and Contributing/License
  sections.

## [1.5.1] - 2026-06-11

### Fixed
- Radarr endpoints: disabled lists are no longer served. `/<user>/<slug>/`
  and `/<user>/watchlist/` now return 404 for lists the user disabled —
  Radarr kept importing items from them.
- Films: `resolve_films` survives Letterboxd remapping a film page to a
  different TMDB entry. Inserting the new film used to crash the sync
  permanently against `UNIQUE(letterboxd_slug)` of the old row, and claiming
  an `imdb_id` already owned by another row crashed against
  `UNIQUE(imdb_id)`. The old row now yields its slug (tombstoned as
  superseded) or its `imdb_id` before the current state of the page is
  persisted.
- Anti-flap: TMDB id remaps now go through the regular anti-flap counter.
  The old rename branch reassigned the new film's slug to the old row and
  crashed full syncs forever against `UNIQUE(letterboxd_slug)`; real slug
  renames (same TMDB id) are already absorbed by `resolve_films`. Also
  implements the documented ad-hoc backstop: on unexplained disappearances,
  a single fetch of `/{user}/films/` page 1 runs before the write
  transaction; confirmed TMDB ids are marked watched (`source=films-page`)
  and removed without waiting for the confirmation threshold.
- Scheduler: periodic scrape jobs now run under `with_scrape_audit`, so they
  create `scrape_runs` and mark `last_sync_status=error` on failure — the
  dashboard was blind to all periodic activity and a persistent failure read
  as a stale success. On startup, RUNNING runs orphaned by a crash are marked
  as error (fixes perpetual spinners and toggles that never relaunched a
  sync), and a daily job prunes `scrape_runs` older than 30 days.
- Custom lists: `recalculate()` with `max_items=NULL` only removed items and
  never added films that now qualify; it now fills with the full eligible
  pool (like init). The PUT endpoint silently cleared fields not present in
  the payload (`maxItems`, filters, rotation, snapshot) — an absent field now
  keeps its current value and an explicit `null` clears it. Invalid `op` /
  `sortOrder` / `excludedUserIds` returned 500, now 400; the slug regex no
  longer accepts a trailing hyphen.
- `validate_username` now reserves `lists` as a username (docs and routing
  already assumed it): a user registered under that name could never be
  served. The reserved-names constant lives in one place and is imported by
  the Radarr routes.
- RSS poll now logs skipped items without `tmdb:movieId` (TV series), as
  documented in the RSS notes. `User-Agent` derives from `__version__` (it
  was pinned at 1.0.0). Removed dead helper `_watchlist_slug_for_user`.

### Added
- MIT `LICENSE` file and GitHub issue templates (bug report / feature
  request), ahead of the repository going public.

### Changed
- `CHANGELOG.md` translated to English and future entries will be written in
  English; `pyproject.toml` description translated as well. Internal docs in
  `.claude/` stay in Spanish.

### Docs
- Sync docs: `watched_films` records when the poll saw the event
  (`first_seen` / `last_seen_watched_at`); the actual viewing date lives in
  `viewing_logs.watched_date`. The docs said otherwise.

## [1.5.0] - 2026-05-23

### Added
- Custom lists: can use other custom lists as a source (`include` or
  `subtract`). Semantics: A sees what B serves to Radarr right now
  (materialized `custom_list_items`), honoring B's `max_items`,
  `sort_order`, `snapshot_interval` and rotation. Eventual consistency — A
  recomposes on its own tick (edit, rotation, snapshot). Server-side cycle
  validation with BFS before saving. The editor shows a new "Custom lists"
  section in the SourcePicker.

### Changed
- `custom_list_sources` migrates to a polymorphic schema: new surrogate PK
  `id` and nullable column `source_custom_list_id` (FK to `custom_lists`).
  Exactly one of `list_id` / `source_custom_list_id` must be set (CHECK
  constraint). Migration 0009. Existing data (all with `list_id` set) is
  preserved.

## [1.4.0] - 2026-05-23

### Added
- Custom lists: new opt-in **"Periodic snapshot"** mode per list. When
  active, the set and order served to Radarr stay frozen between snapshots;
  on the `rotation_tick`, when due, the full set is regenerated from scratch
  honoring the current filters, sources and `sort_order`. Meant for stable
  "top-N by rating" lists that shouldn't reshuffle whenever a recent
  release's rating oscillates. Toggle + interval (hours) in the custom list
  editor; the backend uses `custom_lists.snapshot_interval` /
  `last_snapshot_at`. Takes precedence over rotation when both are active.
  `serialize_custom_list` no longer re-sorts by rating at serve time when
  the list is in snapshot mode — it serves by persisted `position` (which
  `init_items` materializes in ranking order).
- Alembic migration `0008_swap_cooldown_for_snapshot` with the new columns
  on `custom_lists`.

### Removed
- Hard cooldown on Letterboxd scrapes introduced in v1.3.0
  (`lists.min_sync_interval` / `users.watchlist_min_sync_interval`, plus the
  "Min interval between syncs" field in the Lists Advanced panel). It didn't
  solve the right problem: Radarr's output changed because of custom list
  reordering, not scrape frequency. Migration 0008 drops the columns; the
  code that used them was removed from the scheduler, endpoint, UI and
  tests.

## [1.3.0] - 2026-05-22

### Added
- Activity page: humanized logs that preserve the technical information.
  Each structlog event is captured structured in the buffer (event, fields,
  exc_info) and translated via a catalog in
  `src/watchlistarr/services/log_messages.py` into a human sentence. The
  `/api/v1/activity` endpoint additively exposes `event`, `fields`,
  `humanMessage` and `excInfo` — the raw `message` field is kept intact for
  back-compat.
- The Activity.jsx UI renders the human sentence on the main line with
  inline chips for the most relevant fields and a click-to-expand block with
  the full event, all fields and the traceback. Same treatment for
  INFO/WARN/ERROR — the ERROR traceback stays contained in the expandable
  without breaking the collapsed height. The client detects a backend
  restart (`latestSeq < cursor`) and resyncs state without requiring a
  reload.
- The catalog covers ~35 structured events with automatic conversion of
  Letterboxd-style slugs into readable titles
  (`the-thing-with-feathers-2025` → `The Thing With Feathers (2025)`) and
  derivation of `user_label` from `username` with fallback to `user N`.

### Changed
- APScheduler jobs receive a human `name=...` in `add_job()`, so APScheduler
  uses that name in its own messages. The `EXTERNAL_RULES` regexes rewrite
  the technical wrapper
  (`Job "X (trigger: …, next run at: …)" executed successfully` →
  `Job finished — X`) and the `Running job …` pattern is suppressed as
  redundant with the later `executed successfully`. Consistent em-dash
  separator across all human messages.

## [1.2.3] - 2026-05-22

### Fixed
- Custom lists: `rotate()` and `recalculate()` left duplicate `position`
  values between kept and new items when the batch was smaller than the
  list size. Since `position` is not UNIQUE it didn't fail in the DB, but
  the order sent to Radarr (sorted by `position, tmdb_id`) ended up shuffled
  after several rotations. New helper `_reindex_positions()` reassigns
  positions [0..N-1] at the end of both functions, sorting by
  `served_since DESC` (recent items first).
- Custom lists: defense against `year_last_n=0` injected directly into the
  DB (clamped to `>=1` in `_apply_filters`). The endpoint already normalized
  it to None, but the service was exposed to silently producing an empty
  pool.
- Scraping: `sync_list_incremental` and `sync_watchlist_incremental`
  reassigned `position` of existing items based on the index within the
  scraped slice (page 1 + last page), corrupting the order sent to Radarr
  until the next full sync. `_upsert_items` now accepts
  `reassign_positions` (default `True`); incrementals pass `False`.
- DB: migration 0006 adds `rating_desc` to the native enum
  `sort_order_enum`. 0003 had omitted it and the `SortOrder.RATING_DESC`
  feature (introduced in 1.2.0) failed on Postgres with
  `invalid input value for enum`. SQLite was unaffected (enums as VARCHAR).
- Scheduler: `JobScheduler.shutdown` delegated to `asyncio.to_thread` so it
  doesn't block the event loop during the FastAPI lifespan.

### Docs
- `_parse_optional_int` vs `_parse_optional_float`: documented the
  intentional asymmetry (`0` is treated as `None` for ints but `0.0` is
  preserved for floats to support `minRating=0`).

## [1.2.2] - 2026-05-22

### Fixed
- Custom lists: when editing a list and reducing `max_items`, the recompute
  didn't truncate the excess items — the list kept serving the previous size
  to Radarr. `recalculate()` now removes the surplus, choosing what to keep
  according to the configured `sort_order` (top-N by rating in
  `RATING_DESC`, top-N by position in `LETTERBOXD`/`REVERSE`, random in
  `RANDOM`). As defense in depth, `serialize_custom_list` applies
  `LIMIT max_items` at serve time.

## [1.2.1] - 2026-05-22

### Fixed
- `rotation_tick` raised `TypeError: can't compare offset-naive and
  offset-aware datetimes` every hour. SQLite drops tzinfo on `DateTime`
  columns without `timezone=True`, so `last_rotated_at` comes back naive
  when re-read from the DB and adding it to `utcnow()` (aware) broke.
  `rotate()` now normalizes the value to UTC-aware before the arithmetic,
  following the same pattern as `_iso()` in the API. Regression test that
  forces the DB round-trip.

## [1.2.0] - 2026-05-21

### Added
- Custom lists: filters relative to today. `year_last_n` selects films
  released in the last N years (`current_year - N + 1 .. current_year`) and
  `added_last_n_days` filters by the date a film was added to the source
  list. Both are evaluated on every serve to Radarr, so the window moves on
  its own.
- Custom lists: new `SortOrder.RATING_DESC` that sorts by the average
  Letterboxd rating (descending). Requires ratings in the DB; the
  `film_page` scraper now extracts the rating and there is a
  `rating_backfill` job + `scripts/backfill_ratings.py` script to populate
  history.
- Alembic migration `0005_custom_lists_relative_filters` with the new
  columns and the extended enum.
- Integration test `tests/integration/test_rotation.py` covering rotation
  with the new sorts and relative filters.

### Fixed
- `SortOrder.LETTERBOXD`, `REVERSE` and `RANDOM` were ignored in the final
  item selection served to Radarr (it always fell back to the default
  order). All three modes are now honored.

### Changed
- Year filter on custom lists: documented that `year_from`/`year_to` are
  absolute and the new `*_last_n` are relative to today.
- `scripts/smoke.py` covers the new filters and the rating sort.

## [1.1.0] - 2026-05-21

### Added
- Compatibility with Radarr's **Custom Lists** provider in addition to
  **StevenLu Custom**. Each item in the Radarr JSON now includes `id`
  (= `tmdb_id`) alongside `tmdb_id`, `title` and `imdb_id`. Radarr's
  Newtonsoft.Json ignores extra fields, so the same endpoint works against
  both providers; the user picks one in Radarr's UI. Custom Lists resolves
  by direct TMDB ID, without depending on scraping `imdb_id` from the film
  page.
- `scripts/smoke.py` asserts `id == tmdb_id` both on user lists and on
  multi-source custom lists.

### Changed
- `.claude/radarr-custom-list.md` rewritten: documents both Radarr parsers
  (`RadarrListParser` and `StevenLuParser`) side by side, with a single JSON
  example compatible with both.
- README "Connecting Radarr" section mentions both options.

## [1.0.2] - 2026-05-21

### Fixed
- `sqlite3.OperationalError: database is locked` on overlapping scheduler
  jobs. The scrapers held a write transaction open during HTTP fetches to
  Letterboxd; with WAL there is only one writer at a time and the
  `busy_timeout=10s` fired when two jobs (e.g. RSS + watchlist-full) tried
  to write in parallel.

### Changed
- Deep refactor of the scrapers to a **fetch-first / write-last** pattern:
  HTTP and reads outside any transaction, short sessions only for the
  upserts. Affects `rss_watcher`, `films_backstop`, `watchlist`, `lists`
  and `discovery`.
- `resolve_film` replaced by `resolve_films` (batch), which returns flat
  `ResolvedFilm` dataclasses that are safe to cross session boundaries.
- `with_scrape_audit` wraps a coroutine (instead of injecting a session into
  the body); scrapers manage their own internal mini-sessions.
- `scheduler._with_user` / `_with_list` and `onboarding._initial_run`
  adapted to the new `(factory, client, ...)` signature.

### Added
- Regression test `tests/integration/test_scrape_concurrency.py` that runs
  `poll_rss_for_user` and `backstop_films_for_user` in parallel with
  `asyncio.gather` to confirm the lock doesn't reproduce.

## [1.0.1] - 2026-05-21

### Fixed
- The Radarr endpoint now includes `imdb_id` per film. Radarr's parser for
  "Custom List" (`StevenLuParser.cs`) only reads `title` and `imdb_id`;
  serving only `tmdb_id` caused "No results were returned from your import
  list" as soon as Radarr tried to sync.

### Added
- `films.imdb_id` column (Alembic migration `0004_films_imdb_id`, partial
  unique index).
- `parse_film_page` extracts the IMDb ID from Letterboxd's HTML
  (`imdb.com/title/tt…` link).
- `resolve_film` lazily re-resolves a cached film when its `imdb_id` is
  `NULL`.
- `scripts/backfill_imdb.py` script and `services/scrape/imdb_backfill.py`
  module to enrich films already in the DB in bulk.

## [1.0.0] - 2026-05-21

First public release. Includes the project's entire current state.

### Added
- **Multi-user**: automatic discovery of public lists for any Letterboxd
  username added.
- **Custom Lists** with sources (watchlists and lists), union / intersection
  operator, subtract, exclude already-watched, static filters (rating, year)
  and time-based rotation with configurable batch size.
- **Web UI**: React 18 SPA without a build step (Babel-standalone):
  Dashboard, Users, User detail, global Lists, Custom Lists with editor
  (live preview) and Activity with 2s polling and level filters.
- **Radarr endpoints**: `/lists/<slug>/`, `/<username>/watchlist/`,
  `/<username>/<list-slug>/`. JSON array format
  `{tmdb_id, title?, imdb_id?, poster_url?, genres?}` with `ETag` /
  `If-None-Match` support.
- **Anti-flap**: confirmation threshold before deleting an item (default 3
  scrapes; overridable per list from the UI).
- **Scheduling** with in-process APScheduler: incremental + full scrape per
  watchlist and per list, RSS poll, films backstop, discovery, rotation
  tick.
- **Docker image** `maxlainz/watchlistarr` multi-arch (`linux/amd64`,
  `linux/arm64`), a single uvicorn process, SQLite persistence in `/data`
  with automatic Alembic migrations on startup.
- **Versioning system**: SemVer + Conventional Commits, double bump
  (`pyproject.toml` + `__init__.py`), `vX.Y.Z` tags from `main`, automatic
  publication to Docker Hub with `:X.Y.Z`, `:X.Y`, `:latest`, `:sha-<short>`
  tags. Rules and procedure in [`.claude/versioning.md`](.claude/versioning.md).
- **README** in English with quick start, Radarr connection, configuration,
  backup, troubleshooting and a note about the duration of the first scrape.
- **Internal docs** in `.claude/` covering architecture, rules, Letterboxd
  scraping (lists and RSS), the Radarr contract, data model, sync strategy,
  UI features, tech stack and workflows.
