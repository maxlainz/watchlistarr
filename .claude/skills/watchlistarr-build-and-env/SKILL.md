---
name: watchlistarr-build-and-env
description: Toolchain, build, and local environment for watchlistarr — fresh-clone setup with uv, Python 3.12 floor, .env pitfalls (4-slash vs 3-slash DATABASE_URL, pinned USER_AGENT), dependency/lockfile discipline (uv lock, --frozen), Alembic migration chain 0001-0009 and how migrations actually run (in-app at boot), Dockerfile anatomy as coded (stages, python-urllib healthcheck, no curl), docker-compose prod vs dev port truth, CI image publishing (DockerHub + GHCR tag matrix), and the no-build-step vendored frontend. Use when setting up a dev environment, adding/upgrading a dependency, writing a migration, editing the Dockerfile or compose files, or when uv sync/alembic/docker build fails. NOT for running/operating the app or QC loops → watchlistarr-run-and-operate; NOT for CI test steps or smoke.py → watchlistarr-validation-and-qa.
---

# watchlistarr — build, toolchain, and local environment

Ground truth as of 2026-07, v1.5.2 (HEAD `4439c17`). Code beats docs: `tech-stack.md` carries a
stale Dockerfile and a fictional `settings` table — see the standing errata table in
`watchlistarr-docs-and-writing` before trusting any doc claim in this area.

## When to use

- You cloned the repo and need a working local dev environment.
- You are adding, removing, or bumping a dependency in `pyproject.toml`.
- You need to create or understand an Alembic migration, or a migration failed at boot.
- You are editing `Dockerfile`, `docker-compose.yml`, or `docker-compose.dev.yml`.
- You need to know how the published image is built, tagged, and where it lands.
- `uv sync --frozen` fails in CI, or a container is stuck "unhealthy".

## When NOT to use

- Starting/stopping containers, QC loop, admin endpoints, backups → `watchlistarr-run-and-operate`.
- The 5 CI test steps, test suite map, smoke.py → `watchlistarr-validation-and-qa`.
- Env var semantics and settings precedence → `watchlistarr-config-and-flags`.
- Release/tag/merge procedure → `watchlistarr-change-control`.
- Why a past migration exists (full incident stories) → `watchlistarr-failure-archaeology`.

## Local setup from a fresh clone

uv manages the venv AND the Python interpreter. Python floor is 3.12
(`pyproject.toml:6` `requires-python = ">=3.12"`; ruff/mypy both target py312). Run everything
from the repo root.

```bash
# 1. Create .env — required even for docker compose (both compose files declare env_file: .env)
cp .env.example .env
```

Then fix two known traps in the copied `.env` BEFORE first run:

1. **`DATABASE_URL`** — `.env.example:6` ships the Docker value
   `sqlite+aiosqlite:////data/watchlistarr.db` (4 slashes = absolute path `/data/...`, which does
   not exist on your host). For local dev either:
   - change it to the 3-slash relative form `sqlite+aiosqlite:///data/watchlistarr.db` and
     `mkdir -p data` (SQLite creates the file, never the directory; `data/` is gitignored), or
   - delete the line entirely — the code default (`src/watchlistarr/config.py:45`) is already the
     3-slash form; you still need `mkdir -p data`.
2. **`USER_AGENT`** — `.env.example:7` pins `watchlistarr/1.0.0`. The real default derives from
   `__version__` (`config.py:46`), currently 1.5.2. **Delete the line**; keeping it re-pins the
   scraping User-Agent at 1.0.0.

```bash
# 2. Install deps + the project (editable) into ./.venv; uv fetches Python 3.12 if missing
uv sync

# 3. Create/upgrade the SQLite schema (optional before running — see Alembic section — but
#    required before autogenerating a new migration)
uv run alembic upgrade head

# 4. Run the dev server
uv run uvicorn watchlistarr.main:app --reload --port 8080
```

Do NOT write `--port "$HTTP_PORT"`: `.env` is read by pydantic-settings inside the process, it is
never exported to your shell, so `$HTTP_PORT` expands empty. `Settings.http_port`
(`config.py:42`) is dead code — nothing reads it. Pick the port yourself on the uvicorn CLI.

To develop without ever touching live Letterboxd, set `LETTERBOXD_OFFLINE=true` in `.env`
(details in `watchlistarr-config-and-flags`).

Verify: `curl http://127.0.0.1:8080/healthz` → `{"status": "ok", "version": "1.5.2"}`.

## Dependency discipline

- Pin style: **compatible release** `~=` for every runtime and dev dep (`pyproject.toml:9-35`),
  e.g. `fastapi ~= 0.115`. Exact pins live only in `uv.lock`.
- Dev deps are a PEP 735 `[dependency-groups] dev` group (`pyproject.toml:26-35`): ruff, mypy,
  pytest, pytest-asyncio, pytest-cov, respx, types-beautifulsoup4. `uv sync` installs them by
  default; the Docker build uses `--no-dev`.
- **Any `pyproject.toml` dependency change → run `uv lock` → commit `uv.lock` in the SAME
  commit.** CI's first step is `uv sync --frozen` (`.github/workflows/ci.yml:32`) and it fails on
  any pyproject/lock mismatch. Forgetting this once forced an amend + retag + force-push on
  v1.2.2 — ≤2-sentence version here; full story in `watchlistarr-failure-archaeology`.
- `uv.lock` is machine-generated (lockfile `version = 1`, `requires-python = ">=3.12"`); never
  hand-edit. The project itself is locked as `source = { editable = "." }` — `uv sync` installs
  watchlistarr editable, which is why `uv run alembic ...` can import `watchlistarr.config`.

## Alembic migrations

**How they run:** in-app, at every boot. `main.py` lifespan calls
`await asyncio.to_thread(_alembic_upgrade_sync)` which runs `command.upgrade(cfg, "head")`
(`src/watchlistarr/main.py:40-42,52`). There is NO entrypoint shell script and no separate
migration container — starting the app (locally or in Docker) migrates the DB. Running
`uv run alembic upgrade head` manually is idempotent and safe.

Plumbing facts:

- `alembic/env.py:22-23` takes the URL from `get_settings().database_url` — so migrations hit
  whatever `DATABASE_URL`/`.env` resolves to, NOT a URL in `alembic.ini` (there is none).
- `render_as_batch=True` (`alembic/env.py:33,41`) — required for ALTER on SQLite; keep it when
  writing migrations, and prefer `op.batch_alter_table` as the existing revisions do.
- mypy excludes `alembic/versions` (`pyproject.toml:69`); ruff still formats/lints them locally.

**Create a migration** (models changed first, DB at current head). House convention (verified
across all 9 files): revision ids are sequential zero-padded strings, not hashes — pass the next
id with `--rev-id` so no hand-renaming is needed:

```bash
uv run alembic revision --autogenerate --rev-id 0010 -m "short description"
uv run alembic upgrade head
```

Review the autogenerated ops — SQLite partial indexes (`sqlite_where=`) and data migrations are
always hand-written here. Editing rules (never rewrite an already-pushed revision; the revision
ships in the SAME commit as the model change) → `watchlistarr-change-control`.

**The chain, 0001 → 0009** (all in `alembic/versions/`, as of 2026-07 v1.5.2):

| Rev | File | What it did |
|---|---|---|
| 0001 | `0001_initial.py` | Full initial schema: films, scrape_runs, **settings**, users, lists, viewing_logs, watched_films, list_items, sublists, sublist_items. |
| 0002 | `0002_settings_per_entity.py` | **Dropped the `settings` table** (any doc describing it is stale); added nullable per-entity interval override columns to `lists` (incr/full intervals, flap_confirm_scrapes) and `users` (rss/watchlist-incr/watchlist-full/films-backstop/discovery intervals). |
| 0003 | `0003_custom_lists_multisource.py` | Redesigned sublists → `custom_lists` + `custom_list_items` + `custom_list_sources` (include/subtract roles) + `custom_list_excluded_watchers`, with in-place data migration; downgrade raises `NotImplementedError`. |
| 0004 | `0004_films_imdb_id.py` | Added `films.imdb_id` (nullable, partial unique index) because Radarr's StevenLuParser only reads title + imdb_id. |
| 0005 | `0005_custom_lists_relative_filters.py` | Added `custom_lists.year_last_n` and `added_last_n_days` — now-relative filter windows that override the absolute min/max columns. |
| 0006 | `0006_sort_order_rating_desc.py` | Added `rating_desc` to `sort_order_enum` — **Postgres-only `ALTER TYPE`, no-op on SQLite**; fixes the enum value 0003 forgot. |
| 0007 | `0007_min_sync_interval.py` | Added scrape-cooldown columns `lists.min_sync_interval` + `users.watchlist_min_sync_interval`. |
| 0008 | `0008_swap_cooldown_for_snapshot.py` | **Dropped 0007's two columns** (the cooldown was reverted 33 minutes after shipping — wrong mechanism) and added `custom_lists.snapshot_interval` + `last_snapshot_at` (snapshot mode). |
| 0009 | `0009_custom_list_sources_polymorphic.py` | Rebuilt `custom_list_sources`: surrogate `id` PK, `list_id` now nullable, new `source_custom_list_id` FK (custom list as a source of another), CHECK exactly-one-of-the-two. |

The 0007/0008 add-then-drop pair and the 0006 enum patch each carry a lesson: SQLite serializes
enums as VARCHAR without check constraints, so enum/DDL strictness bugs stay invisible until
Postgres. Full incident stories (cooldown revert `c8991da`, enum bug `d8ae10c`) live in
`watchlistarr-failure-archaeology`.

## Dockerfile anatomy — as coded

`tech-stack.md` §Docker shows an **older draft**; trust `Dockerfile` (25 lines). Two stages,
both `python:3.12-slim-bookworm`:

| Stage | Contents |
|---|---|
| `builder` (L1-9) | uv binary copied from `ghcr.io/astral-sh/uv:latest` (distroless copy, version unpinned); copies `pyproject.toml uv.lock README.md` + `src/`; `uv sync --frozen --no-dev` into `/app/.venv` with `UV_COMPILE_BYTECODE=1`. `README.md` and `src/` are needed at build time because the project itself is installed (readme + hatchling wheel target). |
| `runtime` (L11-25) | Copies `/app/.venv`, `src/`, `alembic/`, `alembic.ini` (migrations MUST ship — they run at boot); `mkdir -p /data` + `VOLUME ["/data"]`; `ENV DATABASE_URL="sqlite+aiosqlite:////data/watchlistarr.db"` — **4 slashes, absolute `/data`** (`Dockerfile:15`); `EXPOSE 8080`; `CMD uvicorn watchlistarr.main:app --host 0.0.0.0 --port 8080`. |

**Healthcheck truth** (`Dockerfile:23-24`): a python one-liner —
`python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status==200 else 1)"`
with interval 30s / timeout 5s / start-period 10s. **`curl` is NOT installed in the image.**
tech-stack.md shows a curl healthcheck — copying that into a compose override produces a
container that is permanently `unhealthy`. Keep any healthcheck override python-based.

The container ALWAYS listens on 8080 internally; there is no in-image port knob.

## Compose files: prod vs dev, exact port truth

| | `docker-compose.yml` (prod) | `docker-compose.dev.yml` (dev) |
|---|---|---|
| Image | `image: maxlainz/watchlistarr:latest` (pulled) | `build: .` → tagged `watchlistarr:dev` |
| Container name | `watchlistarr` | `watchlistarr-dev` |
| Ports | `"${HTTP_PORT:-8080}:8080"` | `"${HTTP_PORT:-8080}:8080"` |
| Volume | `./data:/data` | `./data:/data` |
| Env | `env_file: .env` | `env_file: .env` |

- `HTTP_PORT` moves ONLY the host side of the mapping; a fresh clone defaults to **8080** — on
  a fresh clone `curl :8088/healthz` fails. The `:8088` sprinkled through CLAUDE.md/workflows.md
  is owner-box-only; the full port truth and the QC loop live in `watchlistarr-run-and-operate`.
- Both files hard-require `.env` (`env_file:` without `required: false`) — `docker compose up`
  errors on a clone until you `cp .env.example .env`. Inside the container the Dockerfile's
  4-slash `DATABASE_URL` and `.env.example`'s agree, so the Docker path needs no URL edit; the
  `USER_AGENT` deletion from the setup section still applies.

## Image publishing (CI `docker` job)

`.github/workflows/ci.yml:49-101` — runs only after the `qa` job passes, and only on
`push` to `main` or a `v*` tag (`ci.yml:53`). Branch pushes (including `dev`) never publish.

- Multi-arch `linux/amd64,linux/arm64` via QEMU + Buildx, GHA layer cache.
- Pushes to BOTH registries: `maxlainz/watchlistarr` (DockerHub) and
  `ghcr.io/maxlainz/watchlistarr`.
- Tag matrix (`docker/metadata-action`, `ci.yml:86-90`):

| Trigger | Tags produced |
|---|---|
| push to `main` | `latest`, `sha-<short>` |
| push tag `vX.Y.Z` | `X.Y.Z`, `X.Y`, `sha-<short>` |

How and when to cut a release (double version bump, CHANGELOG, tagging from `main`) is owned by
`watchlistarr-change-control` — never tag or push to `main` outside that flow.

## Vendored frontend — no build step, ever

The SPA has **no build pipeline**: `src/watchlistarr/static/index.html` loads `.jsx` files with
`<script type="text/babel">` and `vendor/babel.min.js` compiles them in the browser at page load.
House rule (`.claude/rules.md:58`): **never introduce bundlers or build deps** (Vite, webpack,
npm, node_modules — none exist here).

`src/watchlistarr/static/vendor/` contents and why: `react.min.js`, `react-dom.min.js`,
`babel.min.js`, and `geist/` (Geist/Geist Mono `.woff2` + `geist.css`) are committed so the
Docker image works fully **offline** — no CDN fetches from the container's users. The whole
`static/` tree ships automatically because it lives under the package and the Dockerfile copies
`src/`. Cache-busting `?v=` query strings are appended server-side at startup
(`main.py:109-115`), so UI changes appear after a container restart without hard-refresh.

## What "build" means in this repo

There is **no compile step for the application** — Python sources + in-browser JSX. The
deliverable is the Docker image (section above). A wheel target exists for completeness:
`[build-system]` uses hatchling with `packages = ["src/watchlistarr"]`
(`pyproject.toml:37-42`), so `uv build` would produce a wheel including `static/`, but nothing in
CI or the workflows publishes to PyPI (as of 2026-07, v1.5.2).

## Provenance and maintenance

Re-verify each fact before relying on it after future commits:

| Fact | Command |
|---|---|
| Python floor + pin style + dev deps | `grep -n "requires-python\|~=" pyproject.toml` |
| CI uses frozen sync | `grep -n "uv sync" .github/workflows/ci.yml` |
| Migration chain | `ls alembic/versions/` |
| Migrations run at boot | `grep -n "alembic" src/watchlistarr/main.py` |
| Alembic URL comes from Settings | `grep -n "get_settings\|render_as_batch" alembic/env.py` |
| mypy excludes versions | `grep -n "exclude" pyproject.toml` |
| Healthcheck is python, DATABASE_URL 4-slash, port 8080 | `grep -n "HEALTHCHECK\|DATABASE_URL\|EXPOSE\|CMD" Dockerfile` |
| Compose port mapping + env_file | `grep -n "ports\|env_file\|image\|build" -A1 docker-compose.yml docker-compose.dev.yml` |
| Docker job trigger + tag matrix | `sed -n '49,101p' .github/workflows/ci.yml` |
| `.env.example` traps (4-slash URL, UA pin) | `grep -n "DATABASE_URL\|USER_AGENT" .env.example; grep -in "database_url\|user_agent" src/watchlistarr/config.py` |
| `http_port` still dead code | `grep -rn "http_port" src/ scripts/` |
| No-bundler rule | `grep -n "bundler\|Babel" .claude/rules.md` |
| Vendor contents | `ls src/watchlistarr/static/vendor/` |
| Wheel target | `grep -n "hatchling\|packages" pyproject.toml` |
