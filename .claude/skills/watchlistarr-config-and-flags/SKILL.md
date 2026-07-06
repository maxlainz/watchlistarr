---
name: watchlistarr-config-and-flags
description: The complete reference for watchlistarr configuration — every environment variable (including the easily-missed LETTERBOXD_OFFLINE kill-switch), the <int><s|m|h|d> duration format, the settings-precedence formula (env default vs per-user/per-list DB override), what is settable from the UI/API vs env-only vs DB-edit-only, custom-list per-list knobs, .env pitfalls (4-slash DATABASE_URL for local dev; the legacy USER_AGENT pin in pre-2026-07 .env copies), the HTTP_PORT dead-code truth, and the flap_confirm_scrapes=0 trap. Use when adding/renaming/consuming a setting, debugging "why didn't my env var / interval change take effect", "container won't start after editing .env", or deciding where a new knob should live. NOT for scheduler job mechanics or the anti-flap algorithm itself → use `watchlistarr-architecture-contract`; NOT for docker compose run/QC workflows → use `watchlistarr-run-and-operate`; NOT for uv/Docker image build issues → use `watchlistarr-build-and-env`; NOT for symptom-driven debugging trees → use `watchlistarr-debugging-playbook`.
---

# watchlistarr — configuration and flags

Configuration = **env vars (immutable after boot) + nullable per-entity DB override columns** resolved
in `src/watchlistarr/services/intervals.py`. There is **no `settings` DB table** — created in migration
0001, dropped in 0002. (`.claude/tech-stack.md` previously described one — fixed 2026-07-02; E4 in
`watchlistarr-docs-and-writing`.)

## When to use

- You need the name/type/default of any env var, or where it is consumed in code.
- An interval/setting change "did nothing" and you must determine which tier it lives in (UI-settable, env-only, DB-only).
- The container crashes at startup after editing `.env` (README's #1 troubleshooting item, `README.md:110`).
- You are adding a new setting and must decide: env default, per-entity override column, or both.
- You need the exact payload keys of `POST /api/v1/users/{u}/lists/{id}/settings` or the custom-list knob columns.

## When NOT to use

- How scheduler jobs are built/named, or the full anti-flap removal formula → `watchlistarr-architecture-contract`.
- Running the stack, the `:8088` QC loop, `/admin/refresh` → `watchlistarr-run-and-operate`.
- uv, lockfile, Docker image anatomy, local `.env` bootstrap → `watchlistarr-build-and-env`.
- "Radarr shows nothing" / "sync stuck" diagnosis → `watchlistarr-debugging-playbook`.
- Fixing the docs that contradict this skill → `watchlistarr-docs-and-writing` (owns the errata table).

## 1. THE env-var table (complete, as of 2026-07, v1.5.2)

Source of truth: `src/watchlistarr/config.py:42-58` (class `Settings`). Loaded from process env plus a
`.env` file (`SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")`,
`config.py:35-40`). Env var name = field name uppercased. Unknown vars are silently ignored
(`extra="ignore"`), so a typo in a var *name* fails silently; a typo in a duration *value* crashes (§2).

| Env var | Type | Default | Consumed at | Settable how |
|---|---|---|---|---|
| `HTTP_PORT` | int | `8080` | **Nowhere in app code** — see §1.1 | env only (compose/shell) |
| `LOG_LEVEL` | str | `info` | `logging.py:78` via `main.py:48` — invalid values silently fall back to INFO (`getattr` fallback) | env only, restart |
| `LOG_FORMAT` | str | `plain` | `logging.py:93-96` — `json` selects JSONRenderer, anything else console | env only, restart |
| `DATABASE_URL` | str | `sqlite+aiosqlite:///data/watchlistarr.db` (3-slash, relative) | `db.py:33-39` via `main.py:57`; Docker image overrides with 4-slash absolute (`Dockerfile:15`) — see §7 | env only, restart |
| `USER_AGENT` | str | `watchlistarr/{__version__} (+https://github.com/maxlainz/watchlistarr)` (`config.py:46`) | `services/letterboxd/client.py:40` | env only, restart |
| `LETTERBOXD_OFFLINE` | bool | `false` | `services/letterboxd/client.py:64-65` — any Letterboxd GET raises `LetterboxdOfflineError` | env only, restart |
| `RSS_INTERVAL` | Duration | `15m` | `scheduler.py:113` via `intervals.user_rss_interval` | env only (DB override orphan, §4.3) |
| `WATCHLIST_INCREMENTAL_INTERVAL` | Duration | `1h` | `scheduler.py:141` via `intervals.user_watchlist_incremental` | env default; per-user override via UI/API (§4.1) |
| `WATCHLIST_FULL_INTERVAL` | Duration | `24h` | `scheduler.py:150` via `intervals.user_watchlist_full` | env default; per-user override via UI/API (§4.1) |
| `LISTS_INCREMENTAL_INTERVAL` | Duration | `6h` | `scheduler.py:160` via `intervals.list_incremental` | env default; per-list override via UI/API (§4.1) |
| `LISTS_FULL_INTERVAL` | Duration | `7d` | `scheduler.py:169` via `intervals.list_full` | env default; per-list override via UI/API (§4.1) |
| `FILMS_BACKSTOP_INTERVAL` | Duration | `24h` | `scheduler.py:131` via `intervals.user_films_backstop` | env only (DB override orphan, §4.3) |
| `DISCOVERY_INTERVAL` | Duration | `7d` | `scheduler.py:122` via `intervals.user_discovery` | env only (DB override orphan, §4.3) |
| `ROTATION_TICK_INTERVAL` | Duration | `1h` | `scheduler.py:95` (`rotation-tick` job) | env only, restart |
| `FLAP_CONFIRM_SCRAPES` | int | `3` | `services/scrape/watchlist.py:163`, `services/scrape/lists.py:91` via `intervals.list_flap_threshold` | env default; per-list override via UI/API (§4.1) |

`LETTERBOXD_OFFLINE` was missing from every documentation table until 2026-07-02 (formerly
E22/E28 — the `workflows.md` env table and `ui-features.md` now list it). It exists for smoke/CI
hermeticity (`scripts/smoke.py:394`, `tests/conftest.py:26`); setting it in production makes every
scrape fail loudly.

### 1.1 The truth about HTTP_PORT

`Settings.http_port` (`config.py:42`) is **dead code** — no application code reads it
(`grep -rn "http_port" src/` returns only the definition). The container **always listens on 8080**:
`Dockerfile:25` hardcodes `--port 8080`, `Dockerfile:22` exposes 8080. `HTTP_PORT` only affects:

- the **host-side** compose port mapping: `"${HTTP_PORT:-8080}:8080"` (`docker-compose.yml:7`, `docker-compose.dev.yml:8`);
- the dev shell arg `--port "$HTTP_PORT"` (`.claude/workflows.md:14`) and `scripts/smoke.py:396,415`.

Never change the right-hand `8080` of the compose mapping and never expect `HTTP_PORT` to move the
in-container listener. (`ui-features.md:116` now states this same dead-code truth; it previously
called it "puerto del servidor web" — fixed 2026-07-02; E23.)

## 2. Duration format (canonical)

> **Duration format**: env intervals accept `<int><s|m|h|d>` (e.g. `15m`, `1h`, `7d`) parsed by
> `config.py:_parse_duration`; invalid → startup crash.

Details (verified `config.py:13-31`):

- Regex `^\s*(\d+)\s*([smhd])\s*$`, unit case-insensitive, surrounding whitespace tolerated.
- **The unit is mandatory** — a bare `900` from env arrives as a string, fails the regex, and crashes.
- Invalid value → `ValueError` → pydantic `ValidationError` when `Settings()` is first constructed
  (`get_settings()` at `main.py:47`, inside lifespan) → **the app never comes up**. Symptom: container
  restart loop. This is README's #1 troubleshooting item (`README.md:110`): check
  `docker compose logs watchlistarr` for the `duración inválida` message.
- Applies to the 8 `Duration` fields only; `FLAP_CONFIRM_SCRAPES` is a plain int.

## 3. Settings precedence (canonical)

> **Settings precedence**: interval overrides resolve via `or` — `effective = entity_override
> or env_default` — so a falsy override (NULL **or 0**) falls through to the env default;
> ONLY `flap_confirm_scrapes` resolves via `is None`, so a stored 0 is honored there (the API
> coerces 0→None; anti-flap treats threshold 0 like 1). (`services/intervals.py:10-41`; entity =
> `users` or `lists` nullable columns; env via `config.py`, lru-cached, immutable after boot.)

Concrete resolution walk — which DB column overrides which env default:

| Scheduler concern | Entity override column | Env default | Resolver (`services/intervals.py`) |
|---|---|---|---|
| RSS poll | `users.rss_interval` | `RSS_INTERVAL` | `user_rss_interval` L10-11 |
| Watchlist incremental | `users.watchlist_incremental_interval` | `WATCHLIST_INCREMENTAL_INTERVAL` | `user_watchlist_incremental` L14-15 |
| Watchlist full | `users.watchlist_full_interval` | `WATCHLIST_FULL_INTERVAL` | `user_watchlist_full` L18-19 |
| Films backstop | `users.films_backstop_interval` | `FILMS_BACKSTOP_INTERVAL` | `user_films_backstop` L22-23 |
| List discovery | `users.discovery_interval` | `DISCOVERY_INTERVAL` | `user_discovery` L26-27 |
| List incremental | `lists.lists_incremental_interval` | `LISTS_INCREMENTAL_INTERVAL` | `list_incremental` L30-31 |
| List full | `lists.lists_full_interval` | `LISTS_FULL_INTERVAL` | `list_full` L34-35 |
| Flap threshold | `lists.flap_confirm_scrapes` | `FLAP_CONFIRM_SCRAPES` | `list_flap_threshold` L38-41 |

Override columns: `src/watchlistarr/models/users.py:23-29`, `src/watchlistarr/models/lists.py:49-51`.
All nullable; `NULL` means "use env default".

In practice the intervals can never be zero via API anyway, because `_td_from_hours` maps
`hours <= 0` to `None` (`routes/api/v1.py:62-65`) — the `or` fallthrough matters only for direct
DB edits (§4.3). Flap-threshold-0 semantics: §8.

## 4. The three settability tiers

| Tier | Settings | Mechanism | Takes effect |
|---|---|---|---|
| 1. UI/API-settable | watchlist incr/full interval, list incr/full interval, `flap_confirm_scrapes`; all custom-list knobs (§7) | `POST /api/v1/users/{username}/lists/{list_id}/settings` (`routes/api/v1.py:595-627`); custom lists via `POST/PUT /api/v1/custom-lists*` | Immediately — endpoint calls `scheduler.sync_jobs()` (`v1.py:624-626`), rebuilding all jobs; no restart |
| 2. Env-only | `RSS_INTERVAL`, `FILMS_BACKSTOP_INTERVAL`, `DISCOVERY_INTERVAL`, `ROTATION_TICK_INTERVAL`, **all** env defaults, plus `HTTP_PORT`/`LOG_*`/`DATABASE_URL`/`USER_AGENT`/`LETTERBOXD_OFFLINE` | Edit `.env` / compose env | Only after **restart** (§5) |
| 3. DB-only orphans | `users.rss_interval`, `users.films_backstop_interval`, `users.discovery_interval`, `custom_lists.added_after`, `custom_lists.added_before` | Direct `sqlite3` edit only — **no endpoint or UI sets them** | After next `sync_jobs()` (user orphans) / next materialization (custom-list dates) |

### 4.1 Tier 1 mechanics — `POST /api/v1/users/{u}/lists/{id}/settings`

Payload keys (verified `v1.py:612-622`): `incrementalInterval`, `fullInterval` (integer **hours**;
`0`, `""`, `null` all clear the override → env default, via `_parse_optional_int` + `_td_from_hours`),
`flapConfirmScrapes` (integer). Routing: if the target list is the watchlist
(`source_type is SourceType.WATCHLIST`) the intervals are written to the **user** columns
`watchlist_incremental_interval`/`watchlist_full_interval`; otherwise to the **list** columns.
`flap_confirm_scrapes` is always written to the list row — including the watchlist's own list row.
The UI shows both the override and the env default (`v1.py:144-156` serializes
`defaultIncrementalInterval`, `defaultFullInterval`, `defaultFlapConfirmScrapes`).

### 4.2 Tier 2 — restart required

There is no reload endpoint and no settings table. Changing any env default means editing `.env` and
recreating the process (`docker compose up -d` re-reads `env_file`).

### 4.3 Tier 3 — orphan columns (candidate work: expose or remove)

`users.rss_interval`, `users.films_backstop_interval`, `users.discovery_interval` are honored by the
scheduler (`scheduler.py:113,131,122`) and `custom_lists.added_after`/`added_before` are honored by
`_apply_filters` (`services/custom_lists.py:185-186`), but **no endpoint parses them** — grep
`routes/` for `rss_interval` or `addedAfter` to confirm. Only reachable via direct DB edit.
`Interval` columns on SQLite are stored as **epoch-relative datetimes** (SQLAlchemy `Interval` is
DateTime-backed on SQLite; conventions note in `watchlistarr-debugging-playbook`), so 1 hour is
written as `'1970-01-01 01:00:00.000000'`:

```bash
sqlite3 data/watchlistarr.db "UPDATE users SET rss_interval = '1970-01-01 01:00:00.000000' WHERE letterboxd_username = 'x';"
```

(Prudence: inspect an existing non-NULL override row first and copy its exact format.) Treat as
open candidate work: expose via API or remove the columns. (The docs that misstated this area —
`sync-strategy.md`'s phantom "Advanced" UI for these, `.env.example`'s GUI comment — were fixed
2026-07-02; E18/E32.)

## 5. Env immutability after boot

- `get_settings()` is `@lru_cache(maxsize=1)` (`config.py:61-63`). The `Settings` object is built once
  (first call: `main.py:47`) and every later `get_settings()` returns the same instance. Editing `.env`
  or the process env at runtime changes **nothing** until restart.
- `.env` is read by **pydantic-settings inside the app**, and separately by **docker compose** for
  `${HTTP_PORT:-8080}` interpolation. It is **not exported to your interactive shell**: right after
  `cp .env.example .env`, `echo "$HTTP_PORT"` prints empty, so
  `uv run uvicorn ... --port "$HTTP_PORT"` fails unless you `export HTTP_PORT=8080` first or
  hardcode the port. (`workflows.md` used to document exactly that broken command — fixed
  2026-07-02, E29; it now hardcodes the port and carries this warning.)

## 6. Custom-list per-list knobs (reference table)

Columns on `custom_lists` (`src/watchlistarr/models/custom_lists.py:25-56`), set via
`POST /api/v1/custom-lists` and `PUT /api/v1/custom-lists/{slug}` (`routes/api/v1.py:847-936`).
Behavior details (materialization, rotation, snapshot serving) are owned by
`watchlistarr-architecture-contract` — this is the config surface only.

| Column | API payload key | Two-sentence behavior note |
|---|---|---|
| `op` | `op` | How include sources combine (`union` default, enum `CombinationOp`). Semantics → `watchlistarr-architecture-contract`. |
| `sort_order` | `sortOrder` | Enum `SortOrder`, default `letterboxd`. Honored by `_choose_from_pool` (`services/custom_lists.py:271-298`) — selection is random **only** when `sort_order=RANDOM`. |
| `max_items` | `maxItems` | Cap on materialized items. `0` cannot be set via API (`_parse_optional_int` maps it to `None` = uncapped, `v1.py:650-665`). |
| `min_rating` / `max_rating` | `minRating` / `maxRating` | Float filter on Letterboxd avg rating. `minRating=0` IS preserved (`_parse_optional_float` keeps `0.0`, `v1.py:668-677`). |
| `min_year` / `max_year` | `minYear` / `maxYear` | Absolute year bounds. **Ignored whenever `year_last_n` is set** — both at filter time (`custom_lists.py:169-178`) and at parse time (`v1.py:847-853,917-925` only parse them when `yearLastN` is absent). |
| `year_last_n` | `yearLastN` | Relative window: keeps years `[now.year - N + 1, now.year]`, clamped to N>=1; overrides the absolute year bounds. |
| `added_after` / `added_before` | — **none** | Honored by `_apply_filters` (`custom_lists.py:185-186`) but no endpoint parses them — Tier 3 orphan (§4.3). |
| `added_last_n_days` | `addedLastNDays` | Relative window on `list_items.added_at`: effective `added_after = now - N days`, and it **forces `added_before` to `None`** (`custom_lists.py:181-183`) — relative ignores absolutes. |
| `rotation_enabled` / `rotation_interval` / `rotation_batch_size` | `rotationEnabled` / `rotationInterval` (hours) / `rotationBatchSize` | Rotation is driven by the global `rotation-tick` job (`ROTATION_TICK_INTERVAL`); a list rotates only when `rotation_enabled` AND `rotation_interval` is set (`custom_lists.py:452`). Mechanics → `watchlistarr-architecture-contract`. |
| `snapshot_interval` | `snapshotInterval` (hours) | Non-NULL switches the list to snapshot mode (`services/radarr.py:41`): the served set only refreshes when the interval elapses. Details → `watchlistarr-architecture-contract`. |
| `enabled` | — none | **Dead flag**: default `True`, no endpoint toggles it, the Radarr route never checks it (`routes/api/radarr.py:39-51`). Open candidate work (`watchlistarr-hardening-campaign` track B); now documented in `data-model.md` (formerly E45). |

Note the interval-ish knobs (`rotationInterval`, `snapshotInterval`, plus Tier-1 `incrementalInterval`/
`fullInterval`) are all **integer hours** through the API — the `<int><s|m|h|d>` duration format (§2)
is env-file-only.

## 7. `.env` pitfalls — one live, two historical (fixed in `.env.example` 2026-07-02)

1. **LIVE — 4-slash vs 3-slash `DATABASE_URL`**. `.env.example:6` ships
   `sqlite+aiosqlite:////data/watchlistarr.db` — four slashes = **absolute** path `/data/...`, correct
   inside the container (Dockerfile creates `/data`, compose mounts `./data:/data`). The bare code
   default (`config.py:45`) has three slashes = **relative** `data/...` from the cwd, correct for
   local `uv run` dev. If you copy `.env.example` and run **without Docker**, the 4-slash URL points
   at root-level `/data/` (usually nonexistent) — change it to 3 slashes AND `mkdir -p data`
   (SQLite creates the file, never the directory). Full setup walk: `watchlistarr-build-and-env`.
2. **HISTORICAL, but the trap persists in old copies — the `USER_AGENT` 1.0.0 pin** (formerly E33).
   `.env.example` used to ship an active `USER_AGENT=watchlistarr/1.0.0 (+...)` line; since
   2026-07-02 it is a commented-out `x.y.z` example with a "normalmente dejar sin definir" note.
   Fresh copies are safe, but **any `.env` copied before 2026-07 may still pin the scraping UA at
   1.0.0** — the real default derives from `__version__` (`config.py:46`).
   **Recommendation: delete the `USER_AGENT` line from your `.env`** so the versioned default applies.
3. **HISTORICAL — the "modificables desde la GUI" comment** (formerly E32). `.env.example` used to
   claim env frequencies were GUI-editable after first boot; since 2026-07-02 its comment states the
   truth of §5 (env defaults immutable at runtime; the GUI only sets the per-entity overrides of
   §4.1; `RSS_INTERVAL`/`FILMS_BACKSTOP_INTERVAL`/`DISCOVERY_INTERVAL`/`ROTATION_TICK_INTERVAL`
   env-only). If someone quotes the old comment at you, point them here.

## 8. The `flap_confirm_scrapes = 0` trap

All statements below verified in code:

- **Resolution honors 0**: `list_flap_threshold` uses `if lst.flap_confirm_scrapes is None`
  (`intervals.py:39`), not a falsy check — a stored `0` is returned as the effective threshold.
- **Effect of 0** (`services/scrape/anti_flap.py:146-154`): for an item missing from a full scrape and
  unexplained by anti-flap steps 1-2 (watched_films / films-page backstop — full formula owned by
  `watchlistarr-architecture-contract`), the code does `pending_removal_count += 1` **then** checks
  `>= threshold`. With threshold 0: count becomes 1, `1 >= 0` → **removed on the first unexplained
  miss**. Because the increment precedes the comparison, `0` and `1` behave identically; there is no
  "remove without counting" path.
- **But the API cannot set 0**: `_parse_optional_int` coerces `0` → `None` (`v1.py:650-665`, the
  docstring says so explicitly), so `POST ... {"flapConfirmScrapes": 0}` **clears the override** and
  the env default (3) applies. `0` is reachable only by direct DB edit:
  `sqlite3 data/watchlistarr.db "UPDATE lists SET flap_confirm_scrapes = 0 WHERE id = <id>;"`.
- Net: if someone reports "items vanish after one missed scrape", check the DB for a 0/1 threshold —
  the UI can never have set it to 0.

## Provenance and maintenance

Verified 2026-07 at v1.5.2 (HEAD `4439c17`) by reading code only. Re-verify commands:

| Fact | Re-verify |
|---|---|
| Env-var names/types/defaults (§1) | `sed -n '34,63p' src/watchlistarr/config.py` |
| `http_port` dead code (§1.1) | `grep -rn "http_port" src/ scripts/` — only `config.py:42` in `src/` |
| Container always listens 8080 | `grep -n "port\|EXPOSE" Dockerfile; grep -n "8080" docker-compose*.yml` |
| Duration regex + crash (§2) | `sed -n '13,31p' src/watchlistarr/config.py` |
| Precedence resolvers + `or` vs `is None` (§3) | `cat src/watchlistarr/services/intervals.py` |
| Override columns | `grep -n "Interval\|flap_confirm" src/watchlistarr/models/users.py src/watchlistarr/models/lists.py` |
| Settings endpoint + payload keys (§4.1) | `sed -n '595,627p' src/watchlistarr/routes/api/v1.py` |
| `sync_jobs()` after save | `grep -n "sync_jobs" src/watchlistarr/routes/api/v1.py` |
| Orphan columns unset by API (§4.3) | `grep -rn "rss_interval\|films_backstop_interval\|discovery_interval\|addedAfter\|addedBefore" src/watchlistarr/routes/` |
| `get_settings` lru-cached (§5) | `grep -n "lru_cache" src/watchlistarr/config.py` |
| Custom-list knobs + API keys (§6) | `sed -n '19,56p' src/watchlistarr/models/custom_lists.py; sed -n '847,936p' src/watchlistarr/routes/api/v1.py` |
| Relative filters override absolutes | `sed -n '163,187p' src/watchlistarr/services/custom_lists.py` |
| `.env` pitfalls (§7 — expect `USER_AGENT` commented out and the frequencies comment stating env-immutability, per the 2026-07-02 fixes) | `cat .env.example; grep -n "user_agent\|database_url" src/watchlistarr/config.py` |
| Flap 0 trap (§8) | `sed -n '38,41p' src/watchlistarr/services/intervals.py; sed -n '146,154p' src/watchlistarr/services/scrape/anti_flap.py; sed -n '650,665p' src/watchlistarr/routes/api/v1.py` |
| `LETTERBOXD_OFFLINE` consumers | `grep -rn "letterboxd_offline\|LETTERBOXD_OFFLINE" src/ scripts/ tests/` |

If `config.py`, `intervals.py`, the settings endpoint, or the override columns change, update this
skill **and** the env table consumers listed in §1 in the same change; if the JSON payload of the
settings endpoints changes shape, `scripts/smoke.py` must be updated in the same commit (house rule —
see `watchlistarr-change-control`).
