---
name: watchlistarr-architecture-contract
description: The watchlistarr system map and the numbered invariants (I1-I8) that must never break silently — DB-authoritative serving, the anti-flap removal rule, tmdb_id identity and slug tombstones, fetch-first/write-last transactions, transactional full scrapes, RESERVED_USERNAMES route guards, custom-list materialization, and the rebuilt-from-DB scheduler model. Read this BEFORE designing any change that touches sync, models, routes, the scheduler, or serving order, and cite invariants by number in reviews. NOT for step-by-step debugging (use `watchlistarr-debugging-playbook`), full incident histories (use `watchlistarr-failure-archaeology`), the Radarr payload byte format and parser behavior (use `radarr-integration-reference`), Letterboxd selectors/URLs (use `letterboxd-scraping-reference`), or the env-var table (use `watchlistarr-config-and-flags`).
---

# watchlistarr architecture contract

System map plus the invariants ("the contract") that every change must preserve. Other skills
cite these invariants by number (I1-I8). All anchors verified against code as of 2026-07,
v1.5.2, HEAD one docs commit past the tag.

## When to use

- You are about to add/modify a route, model, migration, scraper, or scheduler job and need to
  know which invariants your change could violate.
- You are reviewing a diff and want a checklist of things that must not regress.
- You are a fresh session and need the one-screen picture of how data flows from Letterboxd to
  Radarr before touching anything.
- Someone proposes "just scrape on request" / "just delete missing items" / "just add a new
  top-level route" — this file is the citation for why not.

## When NOT to use

- Diagnosing a live symptom (stuck sync, 403, empty Radarr list) → `watchlistarr-debugging-playbook`.
- The full story of how an invariant was learned (incidents, shas) → `watchlistarr-failure-archaeology`.
- Exact Radarr JSON bytes, ETag details, StevenLuParser behavior → `radarr-integration-reference`.
- Letterboxd URL/selector/RSS specifics → `letterboxd-scraping-reference`.
- Env vars, defaults, override columns → `watchlistarr-config-and-flags`.
- How to run/operate/trigger jobs → `watchlistarr-run-and-operate`.

## System diagram

```
            HTML: /{u}/lists/, /{u}/watchlist/, /{u}/list/{slug}/,
                  /{u}/films/, /film/{slug}/          RSS: /{u}/rss/
 letterboxd.com ◀───────────────────────────────────────────────────┐
        ▲ LetterboxdClient: 2s min interval PER INSTANCE,           │
        │ retries 5xx x3, 403 = raise immediately (no retry)        │
        │ (services/letterboxd/client.py)                           │
        │                                                           │
  APScheduler (in-process, jobs rebuilt from DB by sync_jobs())     │
  rss-{u} · discovery-{u} · films-backstop-{u} · watchlist-incr/    │
  full-{u} · list-incr/full-{l} · rotation-tick · prune-scrape-runs │
        │  every job wrapped in with_scrape_audit → scrape_runs     │
        ▼                                                           │
  services/scrape/*  — fetch ALL HTTP first ────────────────────────┘
  (discovery, watchlist, lists, rss_watcher,
   films_backstop, film_resolver, anti_flap)
        │  then ONE short write session (no HTTP inside)
        ▼
  SQLite, WAL mode (data/watchlistarr.db)
  films · users · lists · list_items · watched_films · viewing_logs
  custom_lists (+sources +items +excluded_watchers) · scrape_runs
        │                                  │
        │ services/custom_lists.py         │  SELECT only — never scrape
        │ materializes custom_list_items   │  on request (I1)
        │ (create / edit / rotation-tick)  ▼
        │                        FastAPI app (uvicorn, port 8080)
        └───────────────────────▶├─ GET /            SPA shell + cache-buster
                                 ├─ /static/*        React 18, babel-standalone
                                 ├─ GET /healthz     SELECT 1
                                 ├─ /admin/*         inline job trigger, job re-sync
                                 ├─ /api/v1/*        SPA JSON API
                                 └─ Radarr (no auth, registered LAST):
                                    /lists/{slug}/ · /{username}/watchlist/
                                    · /{username}/{slug}/  (catch-all, I6)
```

## Process lifecycle (`src/watchlistarr/main.py`)

Startup order in `lifespan` (main.py:45-71) — order is load-bearing:

1. `get_settings()` + `setup_logging()` + `install_buffer_handler()` (main.py:47-49).
2. **Alembic `upgrade head` at every boot**, in a thread (`_alembic_upgrade_sync` main.py:40-42,
   invoked main.py:52). There is no separate migration step in deploy — the container migrates
   itself. Logging is then re-initialized (main.py:55-56) because alembic's `fileConfig`
   clobbers root-logger handlers.
3. `init_engine(settings.database_url)` (main.py:57) — module-global engine in `db.py`.
4. `fail_interrupted_runs()` (main.py:58, defined services/scrape/audit.py:17): flips any
   `scrape_runs.status='running'` left by a crash/restart to `error`. Without it the UI shows
   perpetual spinners and the list-toggle endpoint refuses immediate syncs.
5. `JobScheduler(...)` → `await scheduler.sync_jobs()` → `scheduler.start()`, stored on
   `app.state.scheduler` (main.py:60-63).
6. Shutdown: `await scheduler.shutdown()` then `dispose_engine()` (main.py:69-70).

App construction (`create_app`, main.py:74-124):

- Routers mounted in order admin, api_v1, radarr (main.py:101-103). **Radarr must stay last** —
  it owns the `/{username}/{slug}/` catch-all (see I6).
- Static mount at `/static` (main.py:77). `GET /` serves `index.html` with a **cache-buster**:
  every `/static/...` src/href gets `?v=<version>-<startup-epoch>` appended by regex at
  app-construction time (main.py:109-115), served `Cache-Control: no-cache` (main.py:117-122).
  Without it babel-standalone caches stale JSX across restarts.
- `GET /healthz` (main.py:79-87): `SELECT 1`; 503 on DB failure.
- Global exception handler (main.py:89-99) re-raises `StarletteHTTPException`, logs everything
  else and returns 500 JSON.

## Module map (`src/watchlistarr/`, verify with `ls -R src/watchlistarr`)

| Path | One line |
|---|---|
| `__init__.py` | `__version__` string (bumped in releases together with pyproject.toml) |
| `main.py` | App factory, lifespan (migrate → repair audit → scheduler), SPA shell, healthz |
| `config.py` | Pydantic `Settings` from env/`.env`, lru-cached (immutable after boot), `Duration` parser |
| `db.py` | Module-global async engine/factory; SQLite pragmas WAL/busy_timeout/FK (db.py:21-30) |
| `scheduler.py` | `JobScheduler` over APScheduler; `sync_jobs()` remove-all-re-add; per-job client + audit wrappers |
| `logging.py` | structlog setup + buffer-capture processor (survives alembic's fileConfig) |
| `models/` | ORM tables — see data-model summary below |
| `routes/api/admin.py` | `POST /admin/refresh/{job_id}` (inline, blocking), `POST /admin/scheduler/sync` |
| `routes/api/radarr.py` | The three unauthenticated Radarr GET routes + ETag/304 handling |
| `routes/api/v1.py` | Entire SPA API: users, list toggles/settings, custom-list CRUD, activity, dashboard |
| `schemas/radarr.py` | `RadarrItem` (`extra="forbid"`) — the served item shape |
| `schemas/letterboxd.py` | Parsed-HTML/RSS DTOs |
| `services/custom_lists.py` | Universe resolution, filters, init/recalculate/rotate/snapshot, cycle detection |
| `services/intervals.py` | Settings-precedence resolution (entity override vs env) |
| `services/radarr.py` | SELECT-to-`RadarrItem` serialization, payload render, ETag |
| `services/onboarding.py` | Background initial-run task on user add (not a wizard) |
| `services/log_buffer.py` / `log_messages.py` | In-memory log ring buffer (2000 lines) + human-message catalog |
| `services/letterboxd/` | HTTP client (rate limit, retries, offline flag) + HTML/RSS parsers |
| `services/scrape/` | Sync workers: discovery, watchlist, lists, rss_watcher, films_backstop, film_resolver, anti_flap, audit, initial_run, imdb/rating backfills |
| `static/` | No-build React 18 SPA: `index.html`, `styles.css`, `src/*.jsx`, `vendor/` |

Outside the package: `alembic/versions/` (9 migrations as of v1.5.2), `scripts/` (smoke.py,
backfills), `tests/`.

## THE INVARIANTS

Cite by number. A change that violates one of these is either a bug or a deliberate breaking
change that must go through `watchlistarr-change-control`.

### I1 — The DB is authoritative; Radarr responses are SELECTs, never live scrapes

Every Radarr endpoint reads persisted rows (`services/radarr.py:17-29,32-56`) — no HTTP happens
in a request handler. Consequences: served output is stable across Letterboxd outages; a scrape
failure never produces an empty response (the previous state keeps being served); latency is a
single indexed SELECT (`ix_list_items_list_position` covers it — see
`watchlistarr-proof-and-analysis-toolkit` Recipe 6; unmeasured beyond that). Never add
on-request scraping "for freshness" — freshness is the scheduler's job.

### I2 — Anti-flap removal rule (additions instant, removals need proof)

Canonical formula (applies ONLY to full scrapes; incremental scrapes never remove):
when a full scrape finds an item in `list_items` but not in the scrape result —
(1) if owner has `(user_id, tmdb_id)` in `watched_films` → remove immediately;
(2) else ad-hoc fetch `/{user}/films/` page 1 (before the write transaction): if present → insert
`watched_films` with `source='films-page'` and remove immediately;
(3) else `pending_removal_count += 1`; remove only when `pending_removal_count >=` effective
flap threshold (list's `flap_confirm_scrapes` override, else env `FLAP_CONFIRM_SCRAPES`, default 3);
(4) reappearance in ANY scrape resets `pending_removal_count = 0`.
(`services/scrape/anti_flap.py` — reconcile at anti_flap.py:88-154, backstop fetch at
anti_flap.py:50-85, counter reset in `_upsert_items`, services/scrape/watchlist.py:76)

Rationale for the asymmetry: an add is cheap and reversible (Radarr queues a movie; removing it
later is a no-op if unmonitored), but a removal can make Radarr **delete media and files** — so
removal requires either proof the owner watched it or `threshold` consecutive full-scrape
misses. A transient parse failure or Letterboxd hiccup must never translate into deletions.
Historical grounding (TMDB-remap crash, `2be042c`/`a6b8dca`, v1.5.1): see
`watchlistarr-failure-archaeology`.

### I3 — Identity: tmdb_id is canonical; slug is a mutable alias; imdb_id is Radarr's key

- `films.tmdb_id` is the PK, no autoincrement (models/films.py:14). A film IS its tmdb_id.
- `letterboxd_slug` is UNIQUE but **mutable**: renames are absorbed by the resolver (match by
  tmdb_id); when Letterboxd remaps a page to a different TMDB entry, the old slug holder is
  re-slugged to the tombstone `"{slug}--superseded-{tmdb_id}"` before assignment
  (`_release_slug`, services/scrape/film_resolver.py:37-54, tombstone at :47). A contested
  imdb_id is nulled on the old holder — the fresh scrape wins (`_release_imdb_id`,
  film_resolver.py:57-72). Never write code that treats slug as a stable key.
- `imdb_id` (UNIQUE, nullable) is enrichment required for Radarr visibility: items without it
  are discarded by Radarr's parser → `radarr-integration-reference`.
- TV is never persisted: the resolver skips anything with `tmdb_type != "movie"` or missing
  tmdb_id (film_resolver.py:126); the RSS watcher requires `tmdb:movieId`.
- Lists are canonically `letterboxd_list_id` (discovery upsert key; list slugs/names are
  refreshed in place). Watchlists have no Letterboxd id — identity is
  `(user_id, source_type=watchlist)`.

### I4 — Fetch-first, write-last; short write sessions; WAL

No HTTP request may run inside a SQLite write transaction. Every scraper fetches and resolves
everything first, then opens one short write session at the end (e.g. full watchlist sync:
services/scrape/watchlist.py — fetch pages → `resolve_films` → `adhoc_films_backstop` → single
write session). Even the anti-flap `/films/` backstop fetch happens before the write session
(anti_flap.py:59-66 docstring). Defensive layer: WAL journal, `busy_timeout=10000`,
`synchronous=NORMAL`, `foreign_keys=ON` on every connect (db.py:21-30), connect
`timeout=30` (db.py:36-37). SQLite has one writer — a long write transaction blocks every
other job and the UI. The "database is locked" incident behind this: `watchlistarr-failure-archaeology`.

### I5 — Full scrapes are transactional; incrementals never delete and never reassign positions

- A full sync's DB effects (upserts + anti-flap reconcile + `last_synced_at`/status stamp) land
  in one write session; any exception during fetch/parse/resolve raises before that session
  opens → partial failure persists nothing.
- Incremental syncs (`sync_watchlist_incremental`, `sync_list_incremental`) fetch only edge
  pages, **never remove items** (no reconcile call), and never rewrite existing positions:
  `_upsert_items(reassign_positions=False)` appends new items at
  `max(existing position) + 1` (services/scrape/watchlist.py:48,58-62; called with
  `reassign_positions=False` by the watchlist incremental at services/scrape/watchlist.py:198
  and the list incremental at services/scrape/lists.py:143). Only full syncs rewrite
  positions to the true list order. Violating this corrupts Radarr serving order (incident
  `25aa6e5` — see `watchlistarr-failure-archaeology`).

### I6 — RESERVED_USERNAMES guards the catch-all route; every new top-level path must be added

The Radarr router (registered last, main.py:101-103) owns `GET /{username}/{slug}/` and
`GET /{username}/watchlist/` — effectively a catch-all over the URL root. Two guards:

- `RESERVED_USERNAMES = frozenset({"all", "api", "admin", "static", "health", "_", "lists"})`
  (services/scrape/initial_run.py:15-17) — checked at user creation
  (`validate_username`, initial_run.py:24-28) AND at request time
  (routes/api/radarr.py:60,88).
- **Rule: any new top-level path segment (e.g. `/metrics`, `/docs2`) MUST be added to
  `RESERVED_USERNAMES` in the same commit**, or a Letterboxd user with that username shadows
  it / your route shadows their list URL.

### I7 — Custom lists materialize into `custom_list_items`; chaining reads the SERVED set

Custom lists are computed by `services/custom_lists.py` (pure DB, no HTTP) and **materialized**
into `custom_list_items` — the Radarr endpoint serves those rows, not a recomputation. Refresh
happens only at: create (`init_items` custom_lists.py:323), edit (`recalculate`
custom_lists.py:375), and the hourly `rotation-tick` (rotate custom_lists.py:451 /
`refresh_snapshot` custom_lists.py:497; snapshot takes precedence, custom_lists.py:527-550).
Scrapes do NOT trigger recomputation — universe changes propagate on the next tick/edit
(eventual consistency, by design).

When custom list A uses custom list B as a source, A reads B's **materialized**
`custom_list_items` — i.e. what B currently serves, after B's `max_items`, sort, rotation and
snapshot — never B's recomputed pool (`_items_by_custom_list`, custom_lists.py:94-116,
docstring says exactly this). Cyclic nesting is rejected by BFS over
`custom_list_sources.source_custom_list_id` (`detect_cycle`, custom_lists.py:626).

### I8 — Scheduler: in-process, jobs never persisted, rebuilt from DB state

APScheduler runs inside the FastAPI process; jobs are **not** persisted anywhere. The whole job
set is derived from DB state by `sync_jobs()` (scheduler.py:83-176): read users + enabled lists
in one session, `remove_all_jobs()`, re-add everything. It is called at boot, after user
add/delete, list toggle, settings save, initial-run completion, and via
`POST /admin/scheduler/sync`. Never mutate individual jobs ad hoc — change the DB and re-sync.

Canonical job ids (scheduler.py:93-174): `rss-{user_id}`, `discovery-{user_id}`,
`films-backstop-{user_id}`, `watchlist-incr-{user_id}`, `watchlist-full-{user_id}`,
`list-incr-{list_id}`, `list-full-{list_id}`, `rotation-tick`, `prune-scrape-runs`.
Operational use (triggering, intervals) → `watchlistarr-run-and-operate`.

Every job body is wrapped in `with_scrape_audit` (services/scrape/audit.py:40; wrappers
scheduler.py:250-320) writing a `scrape_runs` row (running → success/error) — the audit trail
powers UI spinners, the dashboard and the toggle in-flight check. New periodic work MUST be
audit-wrapped; unaudited jobs caused the v1.5.1 blind-spot incident
(`watchlistarr-failure-archaeology`). Each job run constructs its own `LetterboxdClient`
(scheduler.py:260,279,310), so the 2s rate limit is per-instance, not global — a known
fragility tracked by `watchlistarr-hardening-campaign`. Note `trigger_now` (scheduler.py:69-74)
awaits the job inline, bypassing `max_instances=1`.

## Settings precedence

Canonical formula: **Settings precedence**: interval overrides resolve via `or` —
`effective = entity_override or env_default` — so a falsy override (NULL **or 0**) falls through
to the env default; ONLY `flap_confirm_scrapes` resolves via `is None`, so a stored 0 is honored
there (the API coerces 0→None; anti-flap treats threshold 0 like 1). (`services/intervals.py:10-41`;
entity = `users` or `lists` nullable columns; env via `config.py`, lru-cached, immutable after
boot). Full env-var table, override quirks and what is UI-settable → `watchlistarr-config-and-flags`.

## Data-model summary

Detailed doc: `.claude/data-model.md` — broadly accurate, but check the standing errata table
in `watchlistarr-docs-and-writing` before trusting details. PKs verified in `models/` (2026-07).

| Table | PK | Purpose |
|---|---|---|
| `films` | `tmdb_id` (no autoincrement) | Canonical film identity; slug (UNIQUE, mutable), imdb_id (UNIQUE, nullable), rating |
| `users` | `id` | Letterboxd account (`letterboxd_username` UNIQUE) + 5 nullable interval overrides |
| `lists` | `id` | Watchlists AND lists (`source_type`); UNIQUE(user_id, slug) + UNIQUE(letterboxd_list_id); `enabled`, sync status, overrides |
| `list_items` | (`list_id`, `tmdb_id`) | Scraped membership; `position`, `last_seen_at`, `pending_removal_count` (anti-flap state) |
| `watched_films` | (`user_id`, `tmdb_id`) | Watched evidence (source rss / films-page); tmdb_id deliberately NOT FK to films |
| `viewing_logs` | `letterboxd_guid` | Append-only RSS diary; guid PK is the dedup key |
| `custom_lists` | `id` | Definition: slug (UNIQUE), op, max_items, sort_order, filters, rotation, snapshot |
| `custom_list_sources` | `id` | Polymorphic source: exactly one of `list_id` / `source_custom_list_id` (CHECK); role include/subtract |
| `custom_list_items` | (`custom_list_id`, `tmdb_id`) | Materialized served set; `served_since` (rotation FIFO), `position` |
| `custom_list_excluded_watchers` | (`custom_list_id`, `user_id`) | Users whose watched films are excluded |
| `scrape_runs` | `id` | Audit trail: source, target_id, timestamps, running/success/error |

Schema changes go through Alembic (`alembic/versions/`, applied automatically at boot per the
lifecycle above). SQLite masks enum/DDL strictness bugs — see `watchlistarr-failure-archaeology`
(migration 0006 story) and test on Postgres-strict assumptions.

## What would break Radarr users (danger list)

Radarr treats the served list as the source of truth and can be configured to **delete movies
and files** that leave it. These changes cause mass-delete or mass-invisibility downstream —
each is a breaking change ("the Radarr payload is sacred", see `watchlistarr-change-control`)
and most are asserted by `scripts/smoke.py`:

1. **Serving `[]` when data exists** — any bug that empties a SELECT (bad join, wrong filter,
   accidental `enabled` check) reads to Radarr as "everything was removed".
2. **Dropping or renaming `imdb_id`** — Radarr's parser discards items without it; the list
   goes effectively empty without any error → `radarr-integration-reference`.
3. **Changing URL scheme or 404 semantics** — Radarr imports are configured with exact URLs
   (`/lists/{slug}/`, `/{username}/watchlist/`, `/{username}/{slug}/`,
   routes/api/radarr.py:39,54,81); moving a route or turning a 404 into a 200-empty converts
   "config error" into "remove everything".
4. **Changing the JSON shape** (key names, wrapping the array in an object, emitting
   `imdb_id: null` instead of omitting) — `schemas/radarr.py` is `extra="forbid"` and
   `render_payload` uses `exclude_none=True` (services/radarr.py:59-61) for a reason.
5. **Weakening I2 or I5** — deleting on incremental scrapes, lowering the flap threshold
   globally, or removing the films-page backstop turns transient scrape noise into removals.
6. **Unstable serving order + `max_items`** — order changes shuffle which items fall inside the
   serve-time LIMIT (services/radarr.py:50-51), churning Radarr's view between polls.

Full parser behavior, ETag mechanics and payload bytes → `radarr-integration-reference`.

## Provenance and maintenance

Everything above was verified by reading code at v1.5.2 (2026-07). Re-verify before trusting:

| Fact | Re-verify with (from repo root) |
|---|---|
| Lifecycle order, cache-buster, router order | `sed -n '40,124p' src/watchlistarr/main.py` |
| Module map | `ls -R src/watchlistarr` |
| I1 (SELECT-only serving) | `grep -n "client\|httpx" src/watchlistarr/services/radarr.py src/watchlistarr/routes/api/radarr.py` (expect no HTTP client usage) |
| I2 (anti-flap steps + threshold) | `grep -n "pending_removal_count\|threshold" src/watchlistarr/services/scrape/anti_flap.py` |
| I3 (PK + tombstone) | `grep -n "primary_key" src/watchlistarr/models/films.py; grep -n "superseded" src/watchlistarr/services/scrape/film_resolver.py` |
| I4 (pragmas) | `grep -n "PRAGMA" src/watchlistarr/db.py` |
| I5 (append-at-max, no reassign) | `grep -n "reassign_positions\|next_new_position" src/watchlistarr/services/scrape/watchlist.py` |
| I6 (reserved names + request-time check) | `grep -n "RESERVED_USERNAMES" -r src/watchlistarr` |
| I7 (materialized chaining, refresh points) | `grep -n "_items_by_custom_list\|def init_items\|def recalculate\|def rotate\|def refresh_snapshot\|def detect_cycle" src/watchlistarr/services/custom_lists.py` |
| I8 (job ids, audit wrap) | `grep -n '"rotation-tick"\|f"rss-\|f"list-\|with_scrape_audit' src/watchlistarr/scheduler.py` |
| Settings precedence | `cat src/watchlistarr/services/intervals.py` |
| Data-model PKs | `grep -n "primary_key\|__tablename__" src/watchlistarr/models/*.py` |
| Radarr routes/404s | `grep -n "@router.get\|404" src/watchlistarr/routes/api/radarr.py` |
| Migration count | `ls alembic/versions | wc -l` (9 as of v1.5.2) |

If any check disagrees with this file, the code wins — update this skill and report the drift
per `watchlistarr-docs-and-writing`.
