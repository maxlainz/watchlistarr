---
name: watchlistarr-diagnostics-and-tooling
description: Ready-made, read-only diagnostic scripts for a live watchlistarr instance plus sqlite3/curl inspection recipes. Use when you need to INSPECT state right now — check DB health after a crash or restore, find stuck RUNNING scrape_runs, check the scheduler for orphan/stale jobs and a dead scheduler (the live API exposes only the next 5 jobs — full job presence cannot be proven), explain why a specific film is (not) served by a custom list, diff what Radarr receives against what the DB says it should receive, count films missing imdb_id, probe ETag/304 behavior, or run safe read-only curl probes against /api/v1. Keywords - diagnose, inspect, probe, health check, stale job, stuck sync, payload diff, missing film, invisible to Radarr. NOT for symptom-to-fix decision trees (which branch to take next) → use `watchlistarr-debugging-playbook`. NOT for building reproductions, EXPLAIN QUERY PLAN, bisecting, or proving a hypothesis with evidence → use `watchlistarr-proof-and-analysis-toolkit`. NOT for the Radarr contract details themselves → use `radarr-integration-reference`.
---

# watchlistarr diagnostics and tooling

Four stdlib-only Python scripts in `scripts/` next to this file, plus sqlite3 one-liners
and a read-only curl probe list. Everything here is **read-only by construction**: SQLite is
opened with URI `file:...?mode=ro`, HTTP is plain GETs (no POST, no writes). Run any of it
against production without fear.

All scripts share the same conventions:

| Convention | Value |
|---|---|
| Interpreter | plain `python3` (3.12+), **no venv needed** — stdlib only, zero watchlistarr imports |
| `--db PATH` | SQLite file, default `./data/watchlistarr.db` (the compose bind mount `./data:/data`) |
| `--url BASE` | running instance, default `http://127.0.0.1:8080` |
| Exit codes | `0` = OK · `1` = findings printed · `2` = cannot run the analysis: DB missing/unreadable; diff_served: also unreachable `--url` or malformed `--endpoint`; explain_film: also unknown custom-list slug |
| Output | sectioned `== [n] title ==` blocks ending in a numbered `Verdict` list of findings |

> **Honest caveat**: these scripts are new and unexercised against a live instance — if a
> script errors, verify column names against `src/watchlistarr/models/*.py` before trusting
> its verdict. They mirror app queries by hand; the app code is ground truth, not the script.

## When to use

- The dashboard or Radarr looks wrong **right now** and you want facts before theories.
- After a crash, restore, or migration: "is this DB internally healthy?" → `diag_db_health.py`.
- "Why isn't list X syncing?" / "did the scheduler forget a job after I deleted a user?" →
  `diag_scheduler.py`.
- "Film Y should be in custom list Z but Radarr never adds it" → `diag_explain_film.py`.
- "Radarr imports fewer films than the UI shows" / "does the served JSON match the DB?" →
  `diag_diff_served.py`.
- You need a quick, safe SQL or curl probe and don't want to invent one (cheat-sheets below).

## When NOT to use

- You have a symptom and need the **decision tree** (what to check in which order, and the
  fix) → `watchlistarr-debugging-playbook`. That skill may send you back here for a probe.
- You need to **prove** a mechanism (repro with fixtures, respx, lock analysis, EXPLAIN,
  bisect) → `watchlistarr-proof-and-analysis-toolkit`.
- You want the Radarr JSON contract / StevenLuParser behavior explained →
  `radarr-integration-reference`. Scheduler job-id table and admin endpoints in operating
  context → `watchlistarr-run-and-operate`. Env vars and precedence →
  `watchlistarr-config-and-flags`.

## Getting a DB to point at

From repo root on the host running compose, the bind mount means the live file is right there:

```bash
ls -l ./data/watchlistarr.db          # prod and dev compose both mount ./data:/data
```

Docker variant (container names: `watchlistarr` prod, `watchlistarr-dev` dev — see
`docker-compose.yml` / `docker-compose.dev.yml`):

```bash
docker cp watchlistarr:/data/watchlistarr.db /tmp/w.db
# then pass --db /tmp/w.db to any script
```

WAL note: the DB runs in WAL mode, so the freshest commits may live in `watchlistarr.db-wal`.
A lone `docker cp` of the `.db` can be seconds-to-minutes behind. For a fully current
snapshot copy the sidecars too: `docker cp watchlistarr:/data/. /tmp/wdata/` and use
`--db /tmp/wdata/watchlistarr.db`. Pointing `--db` at the live `./data/watchlistarr.db`
is also fine — `mode=ro` cannot block or corrupt the app.

## Script 1 — `diag_db_health.py` (DB integrity and hygiene)

```bash
python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_db_health.py \
    --db ./data/watchlistarr.db          # optional: --stuck-hours 2
```

Reading the output:

| Section | What a finding means |
|---|---|
| SQLite integrity | `integrity_check`/`quick_check` not "ok" or FK violations → restore from backup first, nothing else matters |
| Alembic revision | `alembic_version` != expected head (`0009` as of 2026-07, v1.5.2) → stale DB, or the script's constant needs bumping after a new migration |
| Row counts | a MISSING table → wrong DB file or failed migration |
| Orphan rows | `list_items`/`custom_list_items` without a `films` row are silently dropped at serve (serialization inner-joins `films`). `watched_films` orphans are INFO only — that table has no FK to `films` |
| Films missing imdb_id | served in JSON but **invisible to Radarr** (StevenLuParser discards them). Fix: `uv run python scripts/backfill_imdb.py` |
| Stuck RUNNING scrape_runs | run older than cutoff still `running` → hung job (if app up) or crash leftovers (a restart marks them ERROR via `fail_interrupted_runs`) |
| Lists in error | `lists.last_sync_status='error'` → read `scrape_runs.error` and `/api/v1/activity?level=ERROR` |

## Script 2 — `diag_scheduler.py` (expected vs live jobs + staleness)

```bash
python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_scheduler.py \
    --db ./data/watchlistarr.db --url http://127.0.0.1:8080
    # optional: --env-file ./.env  --grace 2.0  --stuck-hours 2
```

It rebuilds the EXPECTED job set the same way `scheduler.py:sync_jobs()` does
(remove-all-and-re-add from DB state): globals `rotation-tick` + `prune-scrape-runs`; per
user `rss-{user_id}`, `discovery-{user_id}`, `films-backstop-{user_id}`, plus
`watchlist-incr-{user_id}` / `watchlist-full-{user_id}` **only while the user's watchlist
row is enabled**; per enabled `source_type='list'` row `list-incr-{list_id}` /
`list-full-{list_id}`. Operating context for these jobs lives in
`watchlistarr-run-and-operate`.

Reading the output:

| Section | What it tells you |
|---|---|
| [1] Expected jobs | the job ids the scheduler MUST hold, each with its effective interval (per-entity DB override `or` env default, replicating `services/intervals.py`; env defaults from `config.py`, overridable via real env vars or `--env-file`). Disabled lists having no job is correct |
| [2] Live view | `GET /api/v1/dashboard` → `upcoming` entries matched back to expected jobs via the same label mapping as `_job_label` (v1.py). **Limitation**: the dashboard exposes only the NEXT 5 jobs as pretty labels, so this detects orphans (jobs for deleted entities) and a dead scheduler, but cannot prove a specific job is missing. `ORPHAN?` → rebuild with `POST /admin/scheduler/sync` (a write — the script never does it) |
| [3] Stuck RUNNING | same check as db_health, kept here because a hung job explains "nothing is syncing" |
| [4] Lists in error | `last_sync_status='error'` with identity, so you know which job to re-trigger |
| [5] Per-job staleness | last matching `scrape_runs` row age vs `grace ×` effective interval. `STALE` → `POST /admin/refresh/{job_id}` fires it once. Caveats printed inline: incr/full pairs share one audit stream (`source`+`target_id` don't distinguish them — checked against the incremental cadence only), watchlist runs are keyed by the **watchlist list id** not the user id, `prune-scrape-runs` writes no audit row, and runs older than 30 days are pruned |

`--url` unreachable only skips section [2]; exit 2 is reserved for an unopenable DB.

## Script 3 — `diag_explain_film.py` (why is film X (not) in custom list Y?)

```bash
python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_explain_film.py \
    --db ./data/watchlistarr.db --list house --tmdb 603
```

Walks the custom-list funnel stage by stage and stops at the first stage where the film
drops out: [2] no `films` row at all → [3] include sources (`union`/`intersection`
membership, read from the source's **materialized** items) → [4] subtract sources →
[5] excluded watchers (`watched_films`) → [6] static filters (rating/year windows —
NULL rating or year fails any bound; `year_last_n` overrides min/max year; added-date
window) → [8] materialized in `custom_list_items` AND inside the served window
(`max_items` + serve-time sort) AND has an `imdb_id` → exit 0. If eligible but not
materialized, [9] explains the rotation/snapshot state and when it could join. Ends with an
optional non-fatal live probe of `/lists/{slug}/`.

Exit 0 means "served and Radarr-visible"; anything else prints exactly which stage to fix.

## Script 4 — `diag_diff_served.py` (live payload vs DB expectation)

```bash
python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_diff_served.py \
    --db ./data/watchlistarr.db --url http://127.0.0.1:8080 --endpoint /lists/house/
# raw endpoints work too:
#   --endpoint /someuser/watchlist/        --endpoint /someuser/some-list-slug/
```

Reading the output:

| Section | What it tells you |
|---|---|
| [1] Live fetch | HTTP status, ETag, byte size of the real Radarr-facing response |
| [2] DB expectation | recomputed rows mirroring `services/radarr.py`: raw list = `list_items` JOIN `films` ordered by position, unfiltered/uncapped; custom list = `custom_list_items` JOIN `films`, position order — **unless** `sort_order=rating_desc` without `snapshot_interval`, which re-sorts by rating at every serve — then `LIMIT max_items`. Also explains legitimate 404s: unknown slug/user, reserved username, raw list `enabled=0`. (`custom_lists.enabled` is a dead flag — the route never checks it) |
| [3] Diff | count mismatch, membership diff (missing/extra tmdb_ids), order mismatch with first divergence index, and RadarrItem shape violations (keys beyond `id/tmdb_id/title/imdb_id`, `id != tmdb_id`). A one-off diff can be a scrape landing between the HTTP fetch and the DB read — re-run before trusting it |
| [4] No-imdb_id items | served in JSON but discarded by Radarr's StevenLuParser (the `imdb_id` key is omitted when NULL). Fix: `uv run python scripts/backfill_imdb.py` |
| [5] ETag stability | two GETs must return identical body+ETag; then `If-None-Match` must yield 304. Persistent body churn on a `rating_desc` non-snapshot list is the serve-time re-sort churning Radarr — see `radarr-integration-reference` |

## Symptom → script

| Symptom | Run first | Then |
|---|---|---|
| Radarr "No results" / imports fewer than UI shows | `diag_diff_served.py` on the exact URL Radarr polls | `diag_db_health.py` (imdb_id section) |
| A film never appears in a custom list | `diag_explain_film.py` | `watchlistarr-debugging-playbook` if the verdict surprises you |
| A list stopped syncing / stale data | `diag_scheduler.py` ([4],[5]) | `POST /admin/refresh/{job_id}` (manual) |
| Spinner never ends in the UI | `diag_scheduler.py` ([3] stuck RUNNING) | restart clears them; if it recurs → playbook |
| Deleted a user but jobs still fire | `diag_scheduler.py` ([2] orphans) | `POST /admin/scheduler/sync` (manual) |
| Films flicker in/out of Radarr | `diag_diff_served.py` ([5]) | `radarr-integration-reference` + playbook |
| Crash / restore / migration doubt | `diag_db_health.py` | `watchlistarr-proof-and-analysis-toolkit` for migration verification |
| "database is locked" | none of these — go to `watchlistarr-debugging-playbook` | |

## sqlite3 one-liners cheat-sheet

All read-only (`mode=ro`). Column names verified against `src/watchlistarr/models/*.py`
(as of 2026-07, v1.5.2).

```bash
DB='file:./data/watchlistarr.db?mode=ro'

# WAL mode check (expect: wal)
sqlite3 "$DB" 'PRAGMA journal_mode;'

# Top pending removals (anti-flap counters — items on their way out of Radarr)
sqlite3 -header "$DB" "SELECT li.list_id, li.tmdb_id, f.title, li.pending_removal_count
  FROM list_items li LEFT JOIN films f ON f.tmdb_id = li.tmdb_id
  WHERE li.pending_removal_count > 0
  ORDER BY li.pending_removal_count DESC, li.list_id LIMIT 20;"

# Last 20 scrape runs (newest first) with truncated error text
sqlite3 -header "$DB" "SELECT id, source, target_id, status, started_at, ended_at,
  substr(error,1,60) AS error FROM scrape_runs ORDER BY started_at DESC LIMIT 20;"

# Films served-but-invisible-to-Radarr (no imdb_id)
sqlite3 -header "$DB" "SELECT tmdb_id, title, year FROM films
  WHERE imdb_id IS NULL ORDER BY tmdb_id LIMIT 20;"
sqlite3 "$DB" "SELECT COUNT(*) FROM films WHERE imdb_id IS NULL;"

# Which lists feed a custom list (sources with roles)
sqlite3 -header "$DB" "SELECT cl.slug, s.role, s.list_id, s.source_custom_list_id
  FROM custom_list_sources s JOIN custom_lists cl ON cl.id = s.custom_list_id
  ORDER BY cl.slug, s.role;"
```

## Read-only `/api/v1` curl probes

Every probe below is a GET verified against `src/watchlistarr/routes/api/v1.py`,
`main.py` and `routes/api/radarr.py` (as of 2026-07, v1.5.2). Safe to run repeatedly.

```bash
BASE=http://127.0.0.1:8080

curl -s $BASE/healthz                                  # {"status":"ok","version":...}
curl -s $BASE/api/v1/dashboard                         # stats + recentActivity + upcoming(5)
curl -s $BASE/api/v1/users                             # users with lists, sync status, spinners
curl -s $BASE/api/v1/bootstrap                         # users + customLists + dashboard in one
curl -s $BASE/api/v1/custom-lists                      # all custom lists with config + summary
curl -s $BASE/api/v1/custom-lists/<slug>               # one custom list
curl -s "$BASE/api/v1/activity?since=0&level=ERROR"    # error lines from the log ring buffer
curl -s $BASE/api/v1/activity/download                 # full buffer as plain text

# The Radarr-facing surface itself (root-level, unauthenticated):
curl -si $BASE/lists/<slug>/                           # custom list JSON + ETag header
curl -si $BASE/<username>/watchlist/
curl -si $BASE/<username>/<list-slug>/
```

**Not read-only — never script these into diagnostics**: `POST /admin/refresh/{job_id}`
(fires a real scrape against Letterboxd), `POST /admin/scheduler/sync` (rebuilds jobs), and
every `POST/PUT/DELETE` under `/api/v1`. `POST /api/v1/custom-lists/preview` computes a pool
size without persisting, but it is still a POST — use it interactively, not from scripts.

## Provenance and maintenance

The scripts vendor app constants and query shapes by hand. Re-verify each fact at its
source; when the source changes, update the script **in the same change** (note: CI lints
`src tests` only — nothing here is linted or executed by CI, so drift will not be caught
automatically).

| Fact | Re-verify with | On drift, update |
|---|---|---|
| Table/column names | `grep -n "mapped_column\|__tablename__" src/watchlistarr/models/*.py` | all four scripts + cheat-sheet |
| Alembic head `0009` | `ls alembic/versions/ \| sort \| tail -1` (NOT the `grep "^revision"` pipeline — mixed quote styles make `sort` return `'0002'`) | `EXPECTED_ALEMBIC_HEAD` + `APP_TABLES` in `diag_db_health.py` |
| Radarr routes | `grep -n "@router.get" src/watchlistarr/routes/api/radarr.py` | `diag_diff_served.py:classify_endpoint` |
| Serve-time sort/limit semantics | `sed -n '17,56p' src/watchlistarr/services/radarr.py` | `diag_diff_served.py:expected_rows`, `diag_explain_film.py:served_order` |
| RadarrItem keys / exclude_none / ETag | `cat src/watchlistarr/schemas/radarr.py; sed -n '59,66p' src/watchlistarr/services/radarr.py` | `diag_diff_served.py:ALLOWED_ITEM_KEYS` + [5] |
| Scheduler job ids and per-user/per-list keying | `sed -n '83,176p' src/watchlistarr/scheduler.py` | `diag_scheduler.py` expected-jobs block |
| Watchlist audit keyed by list id | `grep -n "with_scrape_audit" src/watchlistarr/scheduler.py` | `diag_scheduler.py` staleness mapping |
| Dashboard `upcoming` keys and labels | `grep -n "_job_label\|upcoming" src/watchlistarr/routes/api/v1.py` | `diag_scheduler.py:job_label` |
| Interval env defaults + `or` fallthrough | `sed -n '48,60p' src/watchlistarr/config.py; cat src/watchlistarr/services/intervals.py` | `diag_scheduler.py:ENV_DEFAULTS` (precedence formula is owned by `watchlistarr-config-and-flags`) |
| RESERVED_USERNAMES | `grep -n "RESERVED_USERNAMES" src/watchlistarr/services/scrape/initial_run.py` | `diag_diff_served.py` |
| Scrape-run retention 30d | `grep -n "SCRAPE_RUN_RETENTION" src/watchlistarr/scheduler.py` | `diag_scheduler.py` |
| /api/v1 probe list | `grep -n "@router\." src/watchlistarr/routes/api/v1.py src/watchlistarr/routes/api/admin.py` | curl section above |

Maintenance triggers: a new migration → bump the db_health constants; a new scheduler job
type → extend `diag_scheduler.py` (expected set + label mapping); any change to the served
JSON is a **breaking change** governed by `watchlistarr-change-control` ("the Radarr payload
is sacred") and must update `diag_diff_served.py` alongside `scripts/smoke.py`.
