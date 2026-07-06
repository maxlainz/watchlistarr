---
name: watchlistarr-debugging-playbook
description: Symptom-to-diagnosis-to-fix decision trees for a live watchlistarr instance. Use when something is broken or weird at runtime — a list stopped syncing, a UI spinner never ends, Letterboxd returns 403 or 5xx, "database is locked", Radarr shows "No results returned" or imports nothing, films flicker in and out of Radarr, an expected film is missing from a custom list, sync errors after a Letterboxd HTML change (selector drift), the web UI is blank, a migration fails at boot, or first sync feels stuck/slow. NOT for full historical incident write-ups → use `watchlistarr-failure-archaeology`; NOT for Letterboxd URL/selector/RSS reference tables → use `letterboxd-scraping-reference`; NOT for the Radarr JSON contract details → use `radarr-integration-reference`; NOT for normal run/deploy/QC workflows → use `watchlistarr-run-and-operate`; NOT for ready-made read-only inspection scripts and probes → use `watchlistarr-diagnostics-and-tooling`; NOT for planning systemic fixes → use `watchlistarr-hardening-campaign`.
---

# watchlistarr debugging playbook

Runbook for diagnosing a live instance. Every command was verified against the code at v1.5.2 (2026-07).
Format per playbook: SYMPTOM → EVIDENCE TO COLLECT → DECISION TREE → VERIFY FIXED.

## When to use

- An operator or the owner reports any symptom in the playbook titles below.
- A scheduled sync failed and you need to find out why before touching code.
- Radarr behaves unexpectedly against a running instance.
- You changed scraping/serving code and want to check nothing regressed live (also run the QC loop in `watchlistarr-run-and-operate`).

## When NOT to use

- You want the full story of a past incident (root cause, sha, lesson) → `watchlistarr-failure-archaeology`.
- You need Letterboxd page anatomy, selectors, or RSS field reference → `letterboxd-scraping-reference`.
- You need the exact Radarr payload contract or StevenLuParser behavior → `radarr-integration-reference`.
- You want to fix the underlying class of problem (global rate limiting, zero-flap guarantees) → `watchlistarr-hardening-campaign`.
- You want ready-made inspection scripts → `watchlistarr-diagnostics-and-tooling`.

## Conventions used below

- **`$PORT`**: host port. Default 8080 (`docker-compose*.yml` map `${HTTP_PORT:-8080}:8080`; in-container port is always 8080). Determine it: `PORT=$(grep -oE '^HTTP_PORT=[0-9]+' .env 2>/dev/null | cut -d= -f2); PORT=${PORT:-8080}` — a fresh clone is 8080; the owner's :8088 QC caveat → `watchlistarr-run-and-operate`.
- **Container name**: `watchlistarr` (prod compose) or `watchlistarr-dev` (dev compose). Substitute accordingly.
- **DB file**: on the host at `./data/watchlistarr.db` (compose volume `./data:/data`). Local non-Docker dev defaults to the relative `data/watchlistarr.db` (`config.py:45`). The image has no `sqlite3` CLI — run `sqlite3` on the host. WAL mode means `-wal`/`-shm` sidecars are normal.
- **Inspect read-only** to avoid taking locks: `sqlite3 "file:data/watchlistarr.db?mode=ro"`. Only write to the DB with the app stopped, or accept that the app retries via `busy_timeout=10000` (`db.py:26`).
- **Timestamps** are naive UTC. `Interval` override columns on SQLite are stored as epoch-relative datetimes (SQLAlchemy `Interval`), so a raw `1970-01-01 06:00:00.000000` means "6 hours".
- The **activity ring buffer** (`GET /api/v1/activity`) holds max 2000 lines in memory and is lost on restart (`services/log_buffer.py:35`) — for anything older, use `docker logs` or `scrape_runs`.

## First 5 minutes — triage box

Run these before anything else. Docker flavor first; local-dev equivalent noted where it differs.

```bash
PORT=$(grep -oE '^HTTP_PORT=[0-9]+' .env 2>/dev/null | cut -d= -f2); PORT=${PORT:-8080}

# 1. Is the app up and can it reach its DB? Expect {"status":"ok","version":...}; 503 = DB unreachable.
curl -s http://localhost:$PORT/healthz

# 2. Recent errors in the in-memory activity buffer (structured logs, humanized).
curl -s "http://localhost:$PORT/api/v1/activity?since=0&level=ERROR" | python3 -m json.tool | tail -60

# 3. Last 20 audited scrape runs — the ground truth on what synced and what failed.
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT id, source, target_id, status, started_at, ended_at, substr(COALESCE(error,''),1,120)
   FROM scrape_runs ORDER BY started_at DESC LIMIT 20;"

# 4. Error grep over container stdout (local dev: read the uvicorn terminal instead).
docker logs --tail 500 watchlistarr 2>&1 | grep -iE "error|forbidden|locked|traceback|exception"

# 5. Scheduler view: stats, recent activity, next 5 upcoming jobs.
curl -s http://localhost:$PORT/api/v1/dashboard | python3 -m json.tool
```

Scheduler job ids you can trigger inline with `curl -s -X POST http://localhost:$PORT/admin/refresh/{job_id}`:
`rotation-tick`, `prune-scrape-runs`, `rss-{user_id}`, `discovery-{user_id}`, `films-backstop-{user_id}`, `watchlist-incr-{user_id}`, `watchlist-full-{user_id}`, `list-incr-{list_id}`, `list-full-{list_id}` (`scheduler.py:93-174`; the canonical job table lives in `watchlistarr-run-and-operate`). Caution: `/admin/refresh` awaits the job inside the HTTP request — it blocks until done and bypasses the `max_instances=1` guard (`scheduler.py:69-74`), so never double-fire it for the same list.

---

## Playbook 1 — A list stopped syncing / spinner never ends

SYMPTOM: "list X hasn't updated in days", or the UI shows a syncing spinner that never finishes, or toggling a list on does nothing.

EVIDENCE:

```bash
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT id, source, target_id, status, started_at FROM scrape_runs WHERE status='running';"
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT id, user_id, source_type, slug, enabled, film_count, last_synced_at, last_sync_status FROM lists;"
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT id, source, target_id, status, started_at, substr(COALESCE(error,''),1,200)
   FROM scrape_runs WHERE target_id=<LIST_ID> AND source IN ('list','watchlist')
   ORDER BY started_at DESC LIMIT 5;"
curl -s http://localhost:$PORT/api/v1/dashboard | python3 -m json.tool | grep -A3 upcoming
```

DECISION TREE:

- **RUNNING row, but activity buffer shows fresh `film.resolve` lines** → not stuck; film resolution is rate-limited to ~2s/page (Playbook 10). Wait.
- **RUNNING row, hours old, no log activity** → orphaned run. The UI spinner (`_running_scrapes`, `routes/api/v1.py:88-109`) and the toggle's immediate-sync kick (`v1.py:578-591`) both key off RUNNING `scrape_runs`, so an orphan freezes both. Boot normally cleans these (`fail_interrupted_runs`, `main.py:58`, `services/scrape/audit.py:17-37`) — an orphan on a *running* instance means a coroutine died without its audit `_finish`. Fix: **restart the app** (cleanest; boot marks orphans `error("interrupted by restart")`), or with the app stopped: `sqlite3 data/watchlistarr.db "UPDATE scrape_runs SET status='error', ended_at=datetime('now'), error='manual cleanup' WHERE status='running';"`
- **`last_sync_status='error'`** → read the newest `scrape_runs.error` for that `target_id` (any exception in a list/watchlist job also stamps `lists.last_sync_status='error'`, `scheduler.py:241-247`). Route by error text: 403/5xx → Playbook 2; "database is locked" → Playbook 3; parse/ValueError → Playbook 7.
- **No `list-incr-{id}`/`list-full-{id}` job for the list** → jobs exist only for `enabled=1` lists (`scheduler.py:156`), and `watchlist-*` jobs only when the watchlist row is enabled (`scheduler.py:137`). If the list IS enabled but the job is missing, the scheduler is out of sync with the DB: `curl -s -X POST http://localhost:$PORT/admin/scheduler/sync`.
- **List unexpectedly `enabled=0`** → discovery disables lists that vanish from the user's Letterboxd lists index (`services/scrape/discovery.py:81-89`, log event `discovery.disabled_missing`). Either it was really deleted/renamed on Letterboxd, or the index parse silently returned nothing → Playbook 7.
- **Job exists but interval is huge** → per-entity override: `SELECT lists_incremental_interval, lists_full_interval, flap_confirm_scrapes FROM lists WHERE id=<ID>;` and the user columns for watchlists. **Settings precedence**: interval overrides resolve via `or` — `effective = entity_override or env_default` — so a falsy override (NULL **or 0**) falls through to the env default; ONLY `flap_confirm_scrapes` resolves via `is None`, so a stored 0 is honored there (the API coerces 0→None; anti-flap treats threshold 0 like 1). (`services/intervals.py:10-41`)

VERIFY FIXED: `curl -s -X POST http://localhost:$PORT/admin/refresh/list-full-<ID>` (blocks until done), then confirm the newest `scrape_runs` row for that target is `success` and `lists.last_synced_at` moved.

## Playbook 2 — Letterboxd 403 / repeated 5xx

SYMPTOM: scrape runs fail with `403 Forbidden` or 5xx; activity shows `letterboxd.forbidden` or `letterboxd.retry_5xx`.

EVIDENCE:

```bash
curl -s "http://localhost:$PORT/api/v1/activity?since=0" | python3 -m json.tool | grep -B2 -A4 'letterboxd\.'
docker logs --tail 1000 watchlistarr 2>&1 | grep -E "letterboxd.forbidden|letterboxd.retry_5xx|films_backstop_failed"
```

Client behavior (`services/letterboxd/client.py`): **403 is logged (`letterboxd.forbidden`) and raised immediately — no retry** (client.py:91-93). **5xx retries up to 3 attempts** with 1s→2s backoff, logging `letterboxd.retry_5xx` per attempt (client.py:94-98). Rate limit is 2s minimum between requests **per client instance** (client.py:15, 67-71) — but every scheduler job builds its own client (`scheduler.py:260,279,310`), so N concurrent jobs hit Letterboxd at N× the polite rate.

DECISION TREE:

- **Isolated 5xx with successful retry** → transient Letterboxd hiccup; nothing to do.
- **5xx exhausting 3 attempts** → the run fails and is audited as `error`; the next scheduled tick retries naturally. Only investigate if it repeats across hours.
- **One-off 403** → the run hard-fails (anti-bot / Cloudflare challenge). The ad-hoc anti-flap backstop degrades gracefully on fetch failure (`anti_flap.py:73-77`, log `anti_flap.films_backstop_failed`) — no data loss, removals just fall back to counting.
- **Repeated 403 across multiple jobs** → you are being rate-limited or fingerprinted. Do NOT tighten intervals or add retries on 403. Interval hygiene checklist: (1) no aggressive per-list interval overrides (Playbook 1 last branch); (2) `USER_AGENT` env not overridden to something anonymous (default identifies the project, `config.py`); (3) stop the bleeding while you think: set `LETTERBOXD_OFFLINE=true` in `.env` and restart — every `get()` then raises `LetterboxdOfflineError` instead of hitting the network (client.py:64-65). Wait hours before resuming.
- The per-client (not global) rate limit is a known systemic weakness; the fix is campaign work → `watchlistarr-hardening-campaign` track (a). Letterboxd's actual rate-limit/anti-bot reality → `letterboxd-scraping-reference`.

VERIFY FIXED: after backing off (and removing `LETTERBOXD_OFFLINE`), trigger the smallest job — `curl -s -X POST http://localhost:$PORT/admin/refresh/films-backstop-<USER_ID>` (single page fetch) — and confirm `success` in `scrape_runs`.

## Playbook 3 — "database is locked"

SYMPTOM: scrape runs or API requests fail with `sqlite3.OperationalError: database is locked`.

EVIDENCE:

```bash
sqlite3 "file:data/watchlistarr.db?mode=ro" "PRAGMA journal_mode;"   # expect: wal
docker logs --tail 1000 watchlistarr 2>&1 | grep -i "database is locked"
fuser data/watchlistarr.db 2>/dev/null   # who else has the file open (host side)
```

The app sets WAL + `busy_timeout=10000` + `synchronous=NORMAL` + FKs on every connect (`db.py:21-30`) and a 30s connect timeout (`db.py:36-37`). WAL allows one writer + many readers; a lock error means a writer waited >10s.

DECISION TREE:

- **External writer**: a forgotten `sqlite3` shell sitting in a transaction, a backup tool copying the live file, or `scripts/backfill_*.py` running against the same `DATABASE_URL`. Close/finish it. Always inspect with `?mode=ro`.
- **`journal_mode` is not `wal`** → someone replaced/restored the DB file; the app re-applies the pragma on next connect — restart the container.
- **Lock errors during app-only operation** → a code change likely put HTTP inside a write transaction, violating the **fetch-first, write-last** invariant: all scrapers do HTTP fully outside DB transactions and open one short write session at the end (e.g. `sync_watchlist_full`, `services/scrape/watchlist.py:118-168`; the audit wrapper deliberately holds no transaction during the awaited coroutine, `audit.py:46-51`). Review the diff for any `await client.get(...)` inside an open session. This invariant exists because the initial sync once held a write transaction ~25 minutes while fetching HTTP; the real fix was the fetch-first/write-last refactor (`b7a44d2`, v1.0.2) — full story in `watchlistarr-failure-archaeology` (incident 2).

VERIFY FIXED: trigger a full sync of a mid-sized list while browsing the UI (concurrent reads); no new "database is locked" in activity/logs.

## Playbook 4 — Radarr shows "No results returned" or imports nothing

SYMPTOM: Radarr's list test fails, or succeeds but adds zero movies.

EVIDENCE:

```bash
# Probe the EXACT URL Radarr is configured with. The real surface (routes/api/radarr.py:39,54,81):
curl -si "http://localhost:$PORT/lists/<custom-slug>/" | head -5
curl -si "http://localhost:$PORT/<username>/watchlist/" | head -5
curl -si "http://localhost:$PORT/<username>/<list-slug>/" | head -5

# imdb_id coverage per list (Radarr discards items without imdb_id):
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT l.slug, COUNT(*) items, SUM(f.imdb_id IS NULL) missing_imdb
   FROM list_items li JOIN lists l ON l.id=li.list_id JOIN films f ON f.tmdb_id=li.tmdb_id
   GROUP BY l.id;"
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT cl.slug, COUNT(*) items, SUM(f.imdb_id IS NULL) missing_imdb
   FROM custom_list_items ci JOIN custom_lists cl ON cl.id=ci.custom_list_id
   JOIN films f ON f.tmdb_id=ci.tmdb_id GROUP BY cl.id;"
```

(Quick per-list counts; the reference form of the imdb-coverage query — a single UNION over raw + custom lists — lives in `radarr-integration-reference`.)

DECISION TREE:

- **404** → (a) wrong URL shape — it is `/lists/{slug}/`, `/{username}/watchlist/`, `/{username}/{slug}/`; a `/list/<list_id>` route never existed (pre-2026-07 docs claimed one — fixed 2026-07-02; old Radarr configs or notes may still carry it); (b) raw list or watchlist is disabled — raw endpoints 404 when `enabled=0` (`radarr.py:75,100`); note custom lists NEVER 404 on their dead `enabled` flag (`radarr.py:39-51`); (c) username is in `RESERVED_USERNAMES` or unknown.
- **307/redirect in the probe** → the URL lacked the trailing slash. Routes are declared with a trailing slash; configure Radarr with it verbatim.
- **200 with items, Radarr imports nothing** → Radarr's StevenLuParser reads only `title` + `imdb_id`; items without `imdb_id` are silently discarded, and the payload *omits* the key when NULL (`services/radarr.py:59-61` `exclude_none`). Check the `missing_imdb` counts above. Fix: `uv run python scripts/backfill_imdb.py [--limit N]` — run from a repo checkout (the Docker image ships no `scripts/`), with `DATABASE_URL` pointed at the host file, e.g. `DATABASE_URL=sqlite+aiosqlite:///data/watchlistarr.db`; ~2s per film. This was incident 3 (`59ad738`, v1.0.1) — details in `watchlistarr-failure-archaeology`; parser behavior in `radarr-integration-reference`.
- **200 with `[]`** → the list has no rows in the DB: never synced (`last_synced_at` NULL → Playbook 1) or, for a custom list, an empty materialized set → Playbook 6.

VERIFY FIXED: `curl -s http://localhost:$PORT/lists/<slug>/ | python3 -m json.tool | grep -c imdb_id` is close to the item count; re-run the list sync in Radarr and see imports.

## Playbook 5 — Films flickering in/out of Radarr

SYMPTOM: movies get added, removed, re-added across Radarr polls; or the served list order keeps shuffling.

EVIDENCE:

```bash
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT l.id, l.slug, COUNT(*) pending, MAX(li.pending_removal_count) max_count
   FROM list_items li JOIN lists l ON l.id=li.list_id
   WHERE li.pending_removal_count > 0 GROUP BY l.id;"
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT slug, sort_order, max_items, snapshot_interval, rotation_enabled, rotation_batch_size FROM custom_lists;"
sqlite3 "file:data/watchlistarr.db?mode=ro" \
  "SELECT id, slug, flap_confirm_scrapes FROM lists WHERE flap_confirm_scrapes IS NOT NULL;"
# ETag stability probe — run twice, compare:
curl -sI "http://localhost:$PORT/lists/<slug>/" | grep -i etag
```

The anti-flap removal rule (applies ONLY to full scrapes; incremental scrapes never remove): when a full scrape finds an item in `list_items` but not in the scrape result — (1) if owner has `(user_id, tmdb_id)` in `watched_films` → remove immediately; (2) else ad-hoc fetch `/{user}/films/` page 1 (before the write transaction): if present → insert `watched_films` with `source='films-page'` and remove immediately; (3) else `pending_removal_count += 1`; remove only when `pending_removal_count >=` effective flap threshold (list's `flap_confirm_scrapes` override, else env `FLAP_CONFIRM_SCRAPES`, default 3); (4) reappearance in ANY scrape resets `pending_removal_count = 0`. (`services/scrape/anti_flap.py`)

DECISION TREE:

- **Custom list with `sort_order='rating_desc'` and `snapshot_interval` NULL** → this is serve-time churn, not scrape churn: the endpoint re-sorts live by rating and applies `max_items` as a LIMIT (`services/radarr.py:41-51`), so rating updates shuffle which top-N is served between polls. Fix: enable snapshot mode (set `snapshot_interval` via the custom-list editor / PUT) — output is frozen between snapshot refreshes. Scrape-frequency throttling was tried for this and reverted 33 minutes later (the cooldown revert, `c8991da`) because the mechanism was serve-time re-sort, not scrape frequency — see `watchlistarr-failure-archaeology` incident 6 and the invariants in `watchlistarr-architecture-contract`.
- **`flap_confirm_scrapes` override of 0 or 1 on a list** → near-immediate deletion on a single missed scrape. Note `0` IS honored (explicit `is None` check, `services/intervals.py:38-41`). Raise it back to NULL (env default 3) via the list's advanced settings.
- **Broad `pending_removal_count` spike across most of one list** → the full scrape returned a partial/empty result: selector or pagination drift → Playbook 7. The counter is the only fence before mass deletion — treat as urgent.
- **A few items with slowly climbing counters** → normal drain of items genuinely removed on Letterboxd; they delete after `threshold` consecutive full scrapes.
- **Rotation lists cycling items** → by design: each `rotation-tick` removes the `min(rotation_batch_size, pool)` oldest-served items and inserts fresh picks (`services/custom_lists.py:451-494`). If unwanted, disable rotation or use snapshot mode (snapshot takes precedence over rotation, `custom_lists.py:544-549`).

VERIFY FIXED: two consecutive probes of the served endpoint return the same ETag; `pending` counts stay flat across two full syncs.

## Playbook 6 — A film I expect in a custom list isn't there

SYMPTOM: "film X should be in custom list Y but Radarr/the UI doesn't show it."

Walk the resolution funnel with SQL, in this order — stop at the first stage that drops the film. Set `TID=<tmdb_id>` and get `CLID`: `SELECT id FROM custom_lists WHERE slug='<slug>';` (The heredoc delimiter below is unquoted so the shell expands `$TID`/`$CLID`; the `<include list_ids>`-style placeholders must still be replaced by hand.)

```bash
sqlite3 "file:data/watchlistarr.db?mode=ro" <<SQL
-- 0. Is the film resolved at all? (TV shows are silently dropped: tmdb_type != 'movie')
SELECT tmdb_id, title, year, tmdb_type, imdb_id, letterboxd_avg_rating FROM films WHERE tmdb_id=$TID;
-- 1. What are the sources? (role include|subtract; exactly one of list_id / source_custom_list_id)
SELECT role, list_id, source_custom_list_id FROM custom_list_sources WHERE custom_list_id=$CLID;
-- 2a. Is it in the include *lists*?
SELECT list_id FROM list_items WHERE tmdb_id=$TID AND list_id IN (<include list_ids>);
-- 2b. ...or in the include *custom lists*? (reads their MATERIALIZED items — B's cap/rotation shape what A sees)
SELECT custom_list_id FROM custom_list_items WHERE tmdb_id=$TID AND custom_list_id IN (<include cl ids>);
-- 3. Subtract sources: same two queries over the subtract ids — a hit here removes it.
-- 4. Excluded watchers: watched by any of them?
SELECT user_id FROM custom_list_excluded_watchers WHERE custom_list_id=$CLID;
SELECT user_id, source FROM watched_films WHERE tmdb_id=$TID AND user_id IN (<excluded user_ids>);
-- 5. Filters on the custom list row:
SELECT op, min_rating, max_rating, min_year, max_year, year_last_n, added_after, added_before,
       added_last_n_days, max_items, sort_order, snapshot_interval, rotation_enabled
FROM custom_lists WHERE id=$CLID;
-- 6. Is it actually served?
SELECT position, served_since FROM custom_list_items WHERE custom_list_id=$CLID AND tmdb_id=$TID;
SQL
```

DECISION TREE (map stage → cause):

- **Not in `films`** → never resolved (or `tmdb_type != 'movie'` — TV drops out silently, `services/scrape/film_resolver.py:126`). Sync the source list first.
- **`op='intersection'`** → the film must appear in EVERY include set, not just one (`_combine_includes`, `services/custom_lists.py:128-137`).
- **In a subtract source or watched by an excluded watcher** → excluded by design (`resolve_universe`, `custom_lists.py:140-160`).
- **`min_rating` set and `letterboxd_avg_rating` is NULL** → NULL ratings silently fail `>=` (`_apply_filters`, `custom_lists.py:189-190`). Backfill: `uv run python scripts/backfill_ratings.py`.
- **Date filters** (`added_after/before/added_last_n_days`) apply only to films arriving via direct list sources, keyed on `list_items.added_at`; films arriving only via a custom-list source bypass them (`custom_lists.py:199-229`).
- **Passes all filters but absent from `custom_list_items`** → eligible-but-not-chosen: `max_items` cap + `sort_order` pick (`_choose_from_pool`, `custom_lists.py:271-298`), or simply stale — **scrapes never recompute custom lists**; membership only changes on create, PUT (`recalculate`), or the hourly `rotation-tick` (rotate / snapshot refresh). Force it: re-PUT the custom list unchanged (triggers `recalculate`) or `curl -s -X POST http://localhost:$PORT/admin/refresh/rotation-tick` (only touches rotation/snapshot lists, and snapshot lists respect their cooldown).

For a scripted version of this funnel, see the scripts in `watchlistarr-diagnostics-and-tooling` (the "explain film" diagnostic), if present in your checkout.

VERIFY FIXED: the film shows in query 6 and in `curl -s http://localhost:$PORT/lists/<slug>/`.

## Playbook 7 — Selector drift: sync errors after a Letterboxd HTML change

SYMPTOM: sync errors mentioning parse/ValueError; or — the dangerous silent form — `film_count` collapses, page logs show 0 items, `pending_removal_count` spikes list-wide (Playbook 5).

Loud vs silent failure paths (know which you are in):

| Parser | Selector | On drift |
|---|---|---|
| `parse_film_page` (`letterboxd/film_page.py:14`) | `<body data-tmdb-id>` etc. | LOUD only if `<body>` missing (raises); missing attrs → film skipped |
| `parse_list_items` (`letterboxd/lists.py:42`) | `div.react-component[data-item-slug]` | SILENT: returns `[]` → full scrape sees empty list → every item +1 flap counter |
| `parse_total_pages` (`letterboxd/lists.py:54`) | `div.pagination` | SILENT: returns 1 → only page 1 scraped; the rest drain via counter |
| `parse_lists_index` (`letterboxd/lists.py:12`) | `article.list-summary[data-film-list-id]` | SILENT: returns `[]` → discovery disables "vanished" enabled lists → Radarr 404s |

House rule (`.claude/rules.md:81`): if a selector fails, **fail noisily** and log enough context to repair it — never guess alternative structure.

EVIDENCE:

```bash
# Per-page item counts are logged: watchlist.full_sync.page {page, total_pages, page_items}
docker logs --tail 2000 watchlistarr 2>&1 | grep -E "full_sync.page|full_sync|incremental_sync|disabled_missing"
# Reproduce the parse locally against the live page (one polite request):
uv run python -c "
import httpx
from watchlistarr.services.letterboxd.lists import parse_list_items, parse_total_pages
html = httpx.get('https://letterboxd.com/<user>/watchlist/', headers={'User-Agent': 'watchlistarr/1.5.2 (+https://github.com/maxlainz/watchlistarr)'}, follow_redirects=True).text
print('items:', len(parse_list_items(html)), 'pages:', parse_total_pages(html))"
```

DECISION TREE:

- **`scrape_runs.error` shows a parse exception** → loud drift. Fix the parser; capture a fixture (below); done.
- **No errors, but `page_items=0` or `total_pages=1` for a known multi-page list** → silent drift in `parse_list_items` / `parse_total_pages`. Same fix, and check flap counters afterwards (Playbook 5) — reappearing items reset to 0 automatically on the next good scrape (`watchlist.py:76`).
- **Enabled lists suddenly disabled + `discovery.disabled_missing` logs** → `parse_lists_index` drift. Re-enable via UI toggle after fixing (toggle off→on also kicks an immediate full sync, `v1.py:578-591`).

Fixture + test loop: save the live HTML into `tests/fixtures/` alongside the 8 existing captures (as of 2026-07 — `ls tests/fixtures/`; inventory table in `letterboxd-scraping-reference`; loaders in `tests/unit/letterboxd/conftest.py`), update the selector, then iterate: `uv run pytest tests/unit/letterboxd/ -q`. Selector reference tables live in `letterboxd-scraping-reference`. Ship the fix through `watchlistarr-change-control` (full local CI before push).

VERIFY FIXED: parser tests green with the new fixture; trigger a full sync and confirm plausible counts and `SELECT COUNT(*) FROM list_items WHERE list_id=<ID> AND pending_removal_count>0;` returns to ~0.

## Playbook 8 — UI blank / static assets broken

SYMPTOM: the web UI renders a blank page, unstyled page, or stale version.

EVIDENCE: open the browser dev console FIRST (the SPA compiles JSX in-browser with babel-standalone; one syntax error in any `.jsx` kills the whole render). Then:

```bash
curl -s http://localhost:$PORT/ | grep -E 'id="root"|\?v='   # shell + cache-buster present?
curl -so /dev/null -w '%{http_code}\n' http://localhost:$PORT/static/vendor/react.min.js
curl -so /dev/null -w '%{http_code}\n' http://localhost:$PORT/static/styles.css
curl -s http://localhost:$PORT/api/v1/bootstrap | head -c 200   # data layer alive?
```

DECISION TREE:

- **Console shows a Babel/SyntaxError** → broken JSX in one of the eleven `type="text/babel"` script files (`src/watchlistarr/static/index.html:16-26`; plus one inline babel block at :28). Fix the file; no build step exists.
- **Console shows `window.X is undefined`** → components communicate via `window.*` globals and load in a fixed order (`app.jsx` last); a renamed/removed global or reordered script tag breaks the chain.
- **Static 404s** → assets are vendored inside the package at `src/watchlistarr/static/` and mounted at `/static` (`main.py:77`); the image copies `src/` wholesale. A 404 means the file genuinely isn't in the image/checkout — rebuild (`docker compose -f docker-compose.dev.yml up -d --build`).
- **UI is stale after a deploy** → the shell injects `?v=<version>-<startup epoch>` on every static ref at app construction and serves `/` with `Cache-Control: no-cache` (`main.py:105-122`). If old UI persists: view-source and check the `?v=` value changed — if it didn't, the container wasn't actually rebuilt/restarted.
- **UI renders but empty data** → `GET /api/v1/bootstrap` failing; debug that endpoint via triage box step 2.

VERIFY FIXED: hard-reload; dashboard renders, console clean, `?v=` reflects the new startup.

## Playbook 9 — Migration failure at boot / version mismatch

SYMPTOM: container restart-loops; logs show an Alembic error before `watchlistarr.ready`; or healthcheck stays unhealthy.

Boot sequence (`main.py:45-71`): `alembic upgrade head` runs in a thread FIRST at every boot, then engine init, `fail_interrupted_runs`, scheduler. Migration failure = app never comes up.

EVIDENCE:

```bash
docker logs watchlistarr 2>&1 | grep -iB2 -A8 "alembic\|migration\|revision"
docker exec watchlistarr alembic current      # works in-image: alembic/ + alembic.ini ship, URL read from env
docker exec watchlistarr alembic history | head
sqlite3 "file:data/watchlistarr.db?mode=ro" "SELECT version_num FROM alembic_version;"
ls alembic/versions/    # head is 0009 as of 2026-07, v1.5.2
```

Local dev: `uv run alembic current` / `uv run alembic history`.

DECISION TREE:

- **"Can't locate revision"** → the DB was migrated by a NEWER app version than the running image (image rollback). Fix: run the matching-or-newer image. Do NOT `alembic downgrade` casually — migrations 0002 and 0008 DROP columns/tables; downgrades are destructive.
- **Migration crashed midway** → SQLite DDL batches are not atomic; the schema may be partially applied. Restore from backup: stop the app, copy back `watchlistarr.db` (+`-wal`/`-shm` if present). Always snapshot the file trio *with the app stopped* before schema surgery.
- **`{"status":"error","db":"unreachable"}` from healthz / connect errors** → not a migration problem: bad `DATABASE_URL` or missing volume. In-container default is `sqlite+aiosqlite:////data/watchlistarr.db` (4 slashes = absolute `/data/...`); compose must map `./data:/data`. See `watchlistarr-build-and-env` for the `.env` path pitfalls.
- **App up but you suspect drift** → `alembic current` vs the last file in `alembic/versions/` — they must match.

VERIFY FIXED: boot log shows `watchlistarr.ready`, `curl -s localhost:$PORT/healthz` returns ok, `alembic current` = head.

## Playbook 10 — Everything is slow on first sync

SYMPTOM: onboarding a user "hangs" for tens of minutes; spinners for a long time; RUNNING scrape_runs for ages.

This is by design, not a bug. Film identity resolution fetches `/film/{slug}/` once per unknown slug at a minimum 2s spacing (`MIN_INTERVAL_SECONDS=2.0`, `client.py:15`; fetch loop in `film_resolver.py`). The initial run full-syncs **every** discovered list including the watchlist (`services/onboarding.py:89-146`). Expected arithmetic: a 1000-film watchlist ≈ 1000 × 2s ≈ **34+ minutes** of film-page fetches alone, plus list pages — thousands of films means hours. Films that genuinely lack an IMDb link or a rating are re-fetched on every sync that includes them (cache requires both `imdb_id` AND `letterboxd_avg_rating` non-NULL, `film_resolver.py:108`) — a permanent slow tail.

EVIDENCE: steady `film.resolve` lines flowing in the activity buffer = working, not stuck (no lines for minutes → Playbook 1 orphan branch).

DECISION TREE:

- **It's the first sync of a large user** → wait. Do not restart mid-onboarding: the initial run is a fire-and-forget asyncio task; a restart leaves it partial (repaired later by scheduler ticks) and its RUNNING rows get marked error at boot. Do not lower the rate limit — see Playbook 2 and the scraping-etiquette house rules.
- **Steady-state syncs are slow too** → check the slow tail: `sqlite3 "file:data/watchlistarr.db?mode=ro" "SELECT COUNT(*) FROM films WHERE imdb_id IS NULL OR letterboxd_avg_rating IS NULL;"` — run the backfill scripts (Playbook 4/6) to shrink it.
- First-sync latency at scale is campaign track (c) → `watchlistarr-hardening-campaign`. Operating expectations and the onboarding reality → `watchlistarr-run-and-operate`.

VERIFY (that it is progressing, not fixed): `SELECT COUNT(*) FROM films;` grows across minutes; onboarding ends with log `initial_run.background.done` and the lists appear (still `enabled=0`) with items pre-synced.

## Provenance and maintenance

Written 2026-07 against v1.5.2 (HEAD `4439c17`). Every fact here was verified by reading code, not docs. Re-verify before trusting, when the named files change:

| Fact | Re-verify with |
|---|---|
| Radarr URL surface + 404/enabled semantics | `grep -n "@router.get" src/watchlistarr/routes/api/radarr.py` |
| 403 no-retry / 5xx retry / 2s rate limit | `sed -n '85,102p' src/watchlistarr/services/letterboxd/client.py` and `grep -n MIN_INTERVAL src/watchlistarr/services/letterboxd/client.py` |
| Scheduler job ids | `grep -n '"\|f"' src/watchlistarr/scheduler.py \| grep -E 'rss-|discovery-|films-backstop-|watchlist-|list-|rotation-tick|prune'` |
| Orphaned-RUNNING cleanup at boot | `grep -n fail_interrupted_runs src/watchlistarr/main.py src/watchlistarr/services/scrape/audit.py` |
| Anti-flap rule + counter reset | `grep -n "pending_removal_count" src/watchlistarr/services/scrape/anti_flap.py src/watchlistarr/services/scrape/watchlist.py` |
| SQLite pragmas (WAL, busy_timeout) | `grep -n PRAGMA src/watchlistarr/db.py` |
| Table/column names used in SQL above | `grep -n "__tablename__\|mapped_column" src/watchlistarr/models/*.py` |
| Serve-time rating re-sort + LIMIT | `sed -n '32,56p' src/watchlistarr/services/radarr.py` |
| Selector strings | `grep -n "select(\|select_one(" src/watchlistarr/services/letterboxd/*.py` |
| Custom-list funnel stages | `grep -n "def resolve_universe\|def _apply_filters\|def eligible_pool\|def _choose_from_pool\|def rotate\|def refresh_snapshot" src/watchlistarr/services/custom_lists.py` |
| Activity endpoint shape | `sed -n '988,1012p' src/watchlistarr/routes/api/v1.py` |
| Port mapping / container names | `grep -n "ports\|container_name" docker-compose.yml docker-compose.dev.yml` |
| Migration head | `ls alembic/versions/ \| tail -1` |
| Fixture inventory | `ls tests/fixtures/` |

If a line number here has drifted more than a few lines, the anchor file was edited — re-read it before acting on the playbook step. Doc-vs-code discrepancies you find while debugging belong in the errata table owned by `watchlistarr-docs-and-writing`.
