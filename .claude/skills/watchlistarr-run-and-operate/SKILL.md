---
name: watchlistarr-run-and-operate
description: Run and operate watchlistarr day-to-day — start it locally (uvicorn --reload), run the dev-container QC loop (git push + docker compose -f docker-compose.dev.yml up -d --build + verification curls), deploy prod compose, understand the boot sequence (auto-migrations, interrupted-run cleanup, scheduler rebuild), trigger jobs manually (POST /admin/refresh/{job_id}, /admin/scheduler/sync, list toggle), know what really happens when a user is onboarded (full pre-sync of every discovered list), read logs/Activity (structlog, 2000-line ring buffer), check /healthz, determine the real host port (container always listens on 8080; the :8088 QC port is owner-.env-only), back up and restore the SQLite DB, and run the backfill scripts. NOT for diagnosing failures once something is broken → `watchlistarr-debugging-playbook`. NOT for toolchain/build/dependency/.env-pitfall questions (uv, Docker image anatomy, lockfile) → `watchlistarr-build-and-env`. NOT for env-var semantics and settings precedence → `watchlistarr-config-and-flags`.
---

# watchlistarr — run and operate

Runbook for starting, watching, poking, and backing up a watchlistarr instance (as of 2026-07, v1.5.2).

## When to use

- "Start the app locally" / "spin up the dev container" / "deploy this".
- "Force a sync of list X right now" / "rebuild the scheduler jobs".
- "What runs at boot?" / "why did all spinners clear after restart?"
- "What happens when I add a user?" / "why is onboarding taking 40 minutes?"
- "Where are the logs?" / "how do I back up the database?"
- "Films are missing imdb_id/ratings in bulk — how do I backfill?"

## When NOT to use

- A run is failing, Radarr shows nothing, the UI is blank, you see 403s or "database is locked" → `watchlistarr-debugging-playbook`.
- uv/lockfile/Dockerfile/.env format questions → `watchlistarr-build-and-env`.
- What an env var means, duration format, override precedence → `watchlistarr-config-and-flags`.
- Radarr URL/payload contract → `radarr-integration-reference`. Commit/merge/release rules → `watchlistarr-change-control`.

## Port truth — determine `$PORT` first

The container process **always listens on 8080** (hardcoded in `Dockerfile:25`; the `HTTP_PORT` setting is dead code in Python). `HTTP_PORT` only moves the **host-side** compose mapping (`"${HTTP_PORT:-8080}:8080"` in both `docker-compose.yml:7` and `docker-compose.dev.yml:8`) or the `--port` arg you pass to uvicorn locally. The owner's box maps **8088** via an uncommitted `.env` setting `HTTP_PORT=8088` (documented in `workflows.md` §Refresh local since 2026-07-02: their 8080 is taken by another service); a fresh clone defaults to **8080**. Never hardcode 8088 in anything you write.

```bash
PORT=$(sed -n 's/^HTTP_PORT=//p' .env 2>/dev/null); PORT=${PORT:-8080}
echo "$PORT"
```

All commands below assume `$PORT` is set this way and you are at the repo root.

## Run modes

### 1. Local dev (uvicorn, hot reload)

```bash
cp .env.example .env    # first time only; fix DATABASE_URL for local: 3 slashes, see below
uv sync
uv run uvicorn watchlistarr.main:app --reload --port "$PORT"
```

- Migrations auto-apply at boot (see startup sequence) — a separate `uv run alembic upgrade head` is optional.
- `.env.example` ships the Docker 4-slash `DATABASE_URL` (absolute `/data/...`); locally use `sqlite+aiosqlite:///data/watchlistarr.db`. Details on this and other `.env` pitfalls: `watchlistarr-build-and-env`.
- Adding a user from a local instance hits **real Letterboxd**. Set `LETTERBOXD_OFFLINE=true` in `.env` to hard-block all outbound requests (`config.py:47`, `services/letterboxd/client.py:63-65`).

### 2. Dev container QC loop (after every commit on `dev`)

House rule (CLAUDE.md): every code commit on `dev` is pushed and the QC container rebuilt immediately.
**Precondition: the 5-step local gate has passed** (`watchlistarr-change-control` /
`watchlistarr-validation-and-qa`) — never push without it.

```bash
git push origin dev && docker compose -f docker-compose.dev.yml up -d --build
```

Verification (10 s):

```bash
curl -sf "http://127.0.0.1:$PORT/healthz"
curl -sf "http://127.0.0.1:$PORT/api/v1/bootstrap" | jq '.users | length'
```

- Failure → `docker compose -f docker-compose.dev.yml logs -f`, then `watchlistarr-debugging-playbook`.
- The `./data` bind mount survives rebuilds — QC state persists.
- The SPA shell injects a per-boot cache-buster on every `/static/...` reference (`main.py:109-115`), so a plain browser reload shows the new UI; no hard-refresh needed.

### 3. Prod compose

```bash
docker compose up -d                     # image maxlainz/watchlistarr:latest (docker-compose.yml:3)
docker compose logs -f watchlistarr
docker compose pull && docker compose up -d   # update
```

DB persists in `./data` on the host, mounted at `/data`. The image healthcheck is a python-urllib one-liner (`Dockerfile:23-24`) — `curl` is NOT in the image.

## Startup sequence (every boot, `main.py:45-71`)

| # | Step | Anchor | Operational meaning |
|---|---|---|---|
| 1 | `setup_logging` + `install_buffer_handler` | main.py:47-49 | structlog → stdout; ring buffer starts empty (seq resets) |
| 2 | `alembic upgrade head` in a thread | main.py:52 | **Migrations auto-apply at every boot** — no manual step in Docker; a failed migration aborts startup |
| 3 | Logging re-installed | main.py:55-56 | alembic's fileConfig clobbers root handlers; without this, post-boot logs vanish |
| 4 | `init_engine(DATABASE_URL)` | main.py:57 | SQLite pragmas per connection: WAL, busy_timeout=10000, synchronous=NORMAL, FKs ON (db.py:21-30) |
| 5 | `fail_interrupted_runs` | main.py:58 | Any `scrape_runs` still RUNNING → ERROR "interrupted by restart" (services/scrape/audit.py:17-37). Clears perpetual UI spinners and unblocks the toggle's in-flight check |
| 6 | `JobScheduler` → `sync_jobs()` → `start()` | main.py:60-63 | Scheduler is **rebuilt from DB state** (remove-all-and-re-add); nothing about job schedules persists across restarts |
| 7 | Shutdown: `scheduler.shutdown()` (threadpool), `dispose_engine()` | main.py:69-70, scheduler.py:54-58 | In-flight jobs are awaited on clean shutdown; a kill mid-scrape leaves RUNNING rows for step 5 to clean next boot |

## Scheduler: jobs, intervals, visibility

Job ids (`scheduler.py:93-174`) — use these exact strings with `/admin/refresh/`:
`rss-{user_id}`, `discovery-{user_id}`, `films-backstop-{user_id}`, `watchlist-incr-{user_id}`, `watchlist-full-{user_id}`, `list-incr-{list_id}`, `list-full-{list_id}`, `rotation-tick`, `prune-scrape-runs`.

- `watchlist-*` jobs exist only while the watchlist row is enabled (scheduler.py:137); `list-*` pairs exist only per **enabled** list (scheduler.py:156). Disabled list → no job → `/admin/refresh` returns 404.
- All jobs are `IntervalTrigger` with `coalesce=True, max_instances=1` (scheduler.py:186-195) — that per-job-id guard is the **only** concurrency control.
- Intervals: per-user/per-list nullable override columns, else env default — canonical precedence formula and env table live in `watchlistarr-config-and-flags` (`services/intervals.py`).
- `prune-scrape-runs` runs daily (hardcoded, scheduler.py:102) and deletes `scrape_runs` older than 30 days (`SCRAPE_RUN_RETENTION`, scheduler.py:34).

**See upcoming jobs and recent runs** — `GET /api/v1/dashboard` (v1.py:1023-1029; same payload embedded in `/api/v1/bootstrap`):

```bash
curl -s "http://127.0.0.1:$PORT/api/v1/dashboard" | jq '{upcoming, recentActivity}'
```

- `upcoming`: next **5** jobs by `next_run_time` (`upcoming_jobs`, scheduler.py:64-67; labeled + `eta`/`nextRunAt`, v1.py:449-459).
- `recentActivity`: last **12** `scrape_runs` with kind/status/error-prefix (v1.py:398-447). `stats.recentErrors` counts ERROR runs in the last hour (v1.py:388-396).
- For more than 12 runs, query the `scrape_runs` table directly — recipes in `watchlistarr-diagnostics-and-tooling`.

## Manual triggers

There is **NO per-list "Refresh" button in the UI** (README and `.claude/workflows.md` used to claim one — fixed 2026-07-02; E26/E30 in `watchlistarr-docs-and-writing`'s resolved list). The real mechanisms:

### `POST /admin/refresh/{job_id}` — run a job now, inline

```bash
curl -X POST "http://127.0.0.1:$PORT/admin/refresh/list-full-3"
curl -X POST "http://127.0.0.1:$PORT/admin/refresh/watchlist-full-1"
curl -X POST "http://127.0.0.1:$PORT/admin/refresh/rotation-tick"
```

Semantics (`routes/api/admin.py:8-16`, `scheduler.py:69-74`): `trigger_now` **awaits the job function inside the HTTP request** — the curl blocks until the scrape finishes (minutes for big full syncs; keep client timeouts generous). 404 = unknown job id (typo, or the list/watchlist is disabled so no job exists). 503 = scheduler not initialized.

**Warning**: because the run does not go through APScheduler, it **bypasses the `max_instances=1` guard**. Check nothing is already RUNNING for that target before triggering (`recentActivity`, or `syncingListIds` in `GET /api/v1/users`), or two scrapes of the same list can interleave write sessions.

### `POST /admin/scheduler/sync` — rebuild all jobs from DB

```bash
curl -X POST "http://127.0.0.1:$PORT/admin/scheduler/sync"   # → {"jobs": N}
```

Use after editing interval/enabled columns directly in SQLite (the API endpoints already call `sync_jobs()` themselves). Rebuild resets every job's next-run clock.

### List toggle off→on = immediate full sync

`POST /api/v1/users/{username}/lists/{list_id}/toggle` (v1.py:554-592): flips `enabled`, rebuilds jobs, and on off→on spawns an immediate background full sync — **unless** a RUNNING `scrape_run` already exists for that list (v1.py:578-591). This is the UI-reachable way to force a refresh of one list (toggle off, toggle on).

## Onboarding reality — what `POST /api/v1/users` actually does

`POST /api/v1/users {"username": "..."}` validates the username against **live Letterboxd** (400 on failure), creates the row, and spawns a fire-and-forget background task (v1.py:499-532, `schedule_initial_run` onboarding.py:147-156). Re-adding an existing username returns 200 idempotently and does **not** re-run onboarding (v1.py:518-522).

The initial run (`onboarding.py:89-146`), each step audit-wrapped and failure-isolated (one failed step does not stop the rest, `_run_step` onboarding.py:73-86):

1. Ensure the watchlist `lists` row exists (`enabled=False`).
2. Discovery: scrape `/{username}/lists/` — every public list inserted `enabled=False`.
3. Films backstop: page 1 of `/{username}/films/` → `watched_films`.
4. **Full sync of EVERY discovered list, watchlist included** (onboarding.py:121-135). Lists stay `enabled=False` but their items are fully pre-synced — toggling one on later serves instantly (and the toggle kicks another full sync anyway).
5. `scheduler.sync_jobs()`.

**Cost implication**: onboarding a user with many lists scrapes all of them up front. Every film not yet cached in `films` costs one `/film/{slug}/` fetch, and the client enforces a 2 s minimum interval per request (`client.py:15,77-83`). Arithmetic: **N new films ≈ N film-page fetches × 2 s+**, plus list pages — a 2,000-film watchlist on a cold DB is ≈ 4,000 s ≈ 67 minutes for that one list. Tens of minutes is normal; watch progress in the Activity tab. The task is an untracked asyncio task: a restart mid-run abandons it (RUNNING rows cleaned at next boot; the scheduler's regular ticks finish the partial sync).

## Observability

- **Logs**: structlog to stdout. `LOG_FORMAT=plain` (console) or `json`; `LOG_LEVEL` as usual. `docker compose logs -f watchlistarr` is the persistent view.
- **Ring buffer**: in-memory deque, **maxlen 2000 lines** (`services/log_buffer.py:35`), capturing both structlog events and external loggers (APScheduler, uvicorn, alembic). **Volatile — lost on every restart** (seq counter resets; the UI detects this).
- `GET /api/v1/activity?since=<seq>&level=<LEVEL>` → `{lines:[{seq,ts,level,src,message,event,fields,humanMessage,excInfo}], latestSeq}` (v1.py:988-1012). The Activity tab polls it every 2 s (`static/src/pages/Activity.jsx:51`); Dashboard polls `/api/v1/dashboard` every 15 s; Users polls every 3 s while spinners are active.
- `GET /api/v1/activity/download` → plaintext dump of the current buffer (v1.py:1015-1020) — grab this **before** restarting if you need evidence.
- `GET /healthz` (main.py:79-87): executes `SELECT 1`; 200 `{"status":"ok","version":...}` or 503 `{"status":"error","db":"unreachable"}`. It proves process-up + DB-reachable, nothing about scraping health — for that, read `stats.recentErrors` on the dashboard.

## Backup and restore

Single SQLite file: host `./data/watchlistarr.db` (container `/data/watchlistarr.db`). WAL journal mode is set on every connection (`db.py:25`), so `-wal`/`-shm` sidecar files exist while the app runs — a raw copy of only the `.db` from under a live writer can be inconsistent.

**Backup, option A (preferred, no downtime)** — from the host, sqlite3 CLI:

```bash
mkdir -p backups
sqlite3 ./data/watchlistarr.db ".backup 'backups/watchlistarr-$(date +%F).db'"
```

`.backup` takes a consistent snapshot even mid-write (WAL). Run it on the host — the sqlite3 CLI is not in the container image.

**Backup, option B (cold copy)**:

```bash
docker compose down
cp ./data/watchlistarr.db* backups/        # copies .db and any -wal/-shm
docker compose up -d
```

**Restore**: stop the container, replace `./data/watchlistarr.db` with the backup, **delete any stale `watchlistarr.db-wal` / `watchlistarr.db-shm`** left from the previous file, start. Migrations auto-apply at boot, so restoring an older-schema backup upgrades itself.

## Maintenance scripts (host-side one-offs, NOT in the Docker image)

The runtime image copies only `src/`, `alembic/`, `alembic.ini` (`Dockerfile:16-19`) — `scripts/` is absent, so no `docker exec`. Run from a repo checkout on the host, against the same DB file:

```bash
DATABASE_URL="sqlite+aiosqlite:///data/watchlistarr.db" uv run python scripts/backfill_imdb.py --limit 100
DATABASE_URL="sqlite+aiosqlite:///data/watchlistarr.db" uv run python scripts/backfill_ratings.py --limit 100
```

- Only flag: `--limit N` (max films to process; default unlimited). Both scripts hit **real Letterboxd** at ~2 s per film — budget accordingly and prefer `--limit` batches.
- The explicit `DATABASE_URL` override matters: a `.env` copied from `.env.example` points at the Docker-absolute `/data/...` path, which does not exist on the host.
- When you need them: `backfill_imdb.py` when many `films.imdb_id` are NULL (Radarr silently drops payload items without imdb_id); `backfill_ratings.py` when `letterboxd_avg_rating` is NULL in bulk (rating filters/sorts exclude NULL). Neither is scheduled — the resolver backfills lazily during normal syncs; scripts are for catching up a large backlog.
- Safe against a running container: WAL + `busy_timeout=10000` allow a concurrent writer, but avoid running them during a huge full sync.

## Housekeeping the app does for you

- **Boot**: orphaned RUNNING `scrape_runs` → ERROR "interrupted by restart" (main.py:58).
- **Daily**: `prune-scrape-runs` deletes audit rows older than 30 days (scheduler.py:34,375-383) — the dashboard/activity history window is bounded by design.

## Provenance and maintenance

Verified against code at HEAD `4439c17` (v1.5.2), 2026-07. Re-verify before trusting:

| Fact | Command |
|---|---|
| Startup order | `sed -n '45,71p' src/watchlistarr/main.py` |
| Container port hardcoded 8080 | `grep -n 'EXPOSE\|--port' Dockerfile` |
| Compose port mapping default | `grep -n HTTP_PORT docker-compose.yml docker-compose.dev.yml` |
| Job ids | `grep -n '"rotation-tick"\|"prune-scrape-runs"\|-{uid}\|-{lst.id}' src/watchlistarr/scheduler.py` (all 9 ids: 2 global + 7 templated) |
| trigger_now inline semantics | `sed -n '69,74p' src/watchlistarr/scheduler.py` |
| Admin endpoints | `grep -n '@router.post' src/watchlistarr/routes/api/admin.py` |
| Toggle immediate sync | `sed -n '578,592p' src/watchlistarr/routes/api/v1.py` |
| Onboarding full-syncs everything | `sed -n '89,146p' src/watchlistarr/services/onboarding.py` |
| Ring buffer size | `grep -n 'max_lines' src/watchlistarr/services/log_buffer.py` |
| Activity/dashboard endpoints | `grep -n '@router.get' src/watchlistarr/routes/api/v1.py` |
| WAL pragma | `grep -n 'journal_mode' src/watchlistarr/db.py` |
| Retention window | `grep -n 'SCRAPE_RUN_RETENTION' src/watchlistarr/scheduler.py` |
| Backfill script flags | `grep -n 'add_argument' scripts/backfill_*.py` |
| Rate limit 2 s | `grep -n 'MIN_INTERVAL_SECONDS' src/watchlistarr/services/letterboxd/client.py` |
| Scripts absent from image | `grep -n 'COPY' Dockerfile` |
