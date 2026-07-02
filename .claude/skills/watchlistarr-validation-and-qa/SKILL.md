---
name: watchlistarr-validation-and-qa
description: How to validate a watchlistarr change before pushing — the 5 CI steps and every local/CI asymmetry (ruff scope, coverage, uv sync --frozen), the pytest suite map (unit/integration layout, conftest infrastructure, respx HTTP mocking, fixtures), coverage reality (no enforced threshold, which modules are untested), and the deep anatomy of scripts/smoke.py — the only end-to-end safety net — including the exact triggers that force a smoke.py update in the same commit. Use when CI fails, when adding or locating tests, when deciding what to run before a push, or when changing a model, migration, HTTP route, JSON shape, or sort semantics and needing to know which asserts must change with it. NOT for branch/merge/release discipline or classifying a change as breaking → use `watchlistarr-change-control`. NOT for diagnosing a misbehaving live instance → use `watchlistarr-debugging-playbook`. NOT for the Radarr JSON contract details → use `radarr-integration-reference`. NOT for uv/Docker toolchain setup → use `watchlistarr-build-and-env`.
---

# Validation and QA

Everything that gates a watchlistarr change: the 5 CI steps, the pytest suite, and
`scripts/smoke.py`. All paths relative to repo root; all commands run with `uv run` from a synced
checkout (`uv sync` first — see `watchlistarr-build-and-env`).

## When to use

- You are about to push and need the exact pre-push validation commands.
- CI is red and you need to know what each step does and how to reproduce it locally.
- You changed a model, migration, route, JSON shape, or sort semantics and need the list of
  asserts that must be updated in the same commit.
- You are adding a test and need the right fixture pattern and an exemplar to copy.
- You need to know what is and is not covered by tests (before trusting a green run).

## When NOT to use

- Deciding whether a change is breaking, or how to merge/release → `watchlistarr-change-control`.
- A live instance misbehaves (sync stuck, Radarr empty, 403) → `watchlistarr-debugging-playbook`.
- Details of the Radarr payload contract → `radarr-integration-reference`.
- Letterboxd HTML/RSS selectors and fixture provenance → `letterboxd-scraping-reference`.
- Building repro cases or proving a hypothesis → `watchlistarr-proof-and-analysis-toolkit`.

## 1. The 5 CI steps (canonical formula)

**The 5 CI steps** (`.github/workflows/ci.yml`): `uv sync --frozen` then
`uv run ruff check src tests` · `uv run ruff format --check src tests` · `uv run mypy src` ·
`uv run pytest --cov=src/watchlistarr --cov-report=term` · `uv run python scripts/smoke.py`.
House rule adds `scripts` to both ruff invocations locally (CI does not lint scripts — asymmetry
is a known erratum).

The house pre-push one-liner (`.claude/rules.md:21-29`, verbatim):

```bash
uv run ruff check src tests scripts && \
uv run ruff format --check src tests scripts && \
uv run mypy src && \
uv run pytest -q && \
uv run python scripts/smoke.py
```

### Local vs CI asymmetry table

| # | CI step (`.github/workflows/ci.yml`) | Local house command (`.claude/rules.md:24-28`) | Difference |
|---|---|---|---|
| 0 | `uv sync --frozen` (ci.yml:32) | plain `uv sync` | Stale `uv.lock` fails CI only. After any `pyproject.toml` dep change: `uv lock` + commit `uv.lock` in the same commit (rules.md:17). |
| 1 | `uv run ruff check src tests` (ci.yml:35) | `uv run ruff check src tests scripts` | **CI never lints `scripts/`; local does.** Local is strictly stricter. |
| 2 | `uv run ruff format --check src tests` (ci.yml:38) | `uv run ruff format --check src tests scripts` | Same gap. Fix formatting with `uv run ruff format src tests scripts` before committing (rules.md:15). |
| 3 | `uv run mypy src` (ci.yml:41) | identical | `tests/` and `scripts/` are never type-checked anywhere. |
| 4 | `uv run pytest --cov=src/watchlistarr --cov-report=term` (ci.yml:44) | `uv run pytest -q` | CI measures coverage; local does not. **No threshold either way** (§3). Same tests run in both. |
| 5 | `uv run python scripts/smoke.py` (ci.yml:47) | identical | — |

### Which invocation to use when

- **Before every push**: the house one-liner above. Passing it guarantees CI steps 1-2 pass
  (superset scope) and steps 3-5 pass (identical). The one thing it cannot guarantee is step 0 —
  if you touched deps, also run `uv lock` and commit the lockfile. Forgetting this once forced an
  amend + retag + force-push at v1.2.2; full story in `watchlistarr-failure-archaeology`.
- **Reproducing a CI pytest failure or reading coverage**: run the CI form,
  `uv run pytest --cov=src/watchlistarr --cov-report=term-missing`.
- **Iterating on one test**: `uv run pytest tests/integration/test_rotation.py -k <name> -q`.

CI triggers on push to **all** branches and tags `v*.*.*`, plus all PRs (ci.yml:3-8) — `dev`
pushes run the full `qa` job. The `docker` build job is different: see §8.

## 2. Test-suite map

Layout (mirrors `src/watchlistarr/`, per `.claude/rules.md:59`):

```
tests/
  conftest.py            # DB/engine/session/app fixtures (real Alembic per test)
  fixtures/              # 8 static specimens: 7 .html + rss_feed.xml (trimmed real captures)
  unit/                  # no DB, no HTTP (except test_healthz/test_client via TestClient/respx, and test_models.py which uses the real migrated DB)
    letterboxd/          # parser tests, fixture-driven; conftest.py = named fixture loaders
  integration/           # DB + service level + TestClient HTTP; conftest.py = letterboxd client
```

Count tests with a command, not a frozen number:

```bash
grep -rc "def test_" tests/ | grep -v ":0$" | sort -t: -k2 -nr   # per file
grep -r "def test_" tests/ | wc -l                               # total
```

Snapshot (as of 2026-07, v1.5.2): **154 tests — 67 unit / 87 integration**.

| File | Tests | Purpose (one line) |
|---|---|---|
| `tests/unit/test_healthz.py` | 1 | `GET /healthz` returns 200 |
| `tests/unit/test_intervals.py` | 6 | effective-interval resolution (per-entity override vs env default) |
| `tests/unit/test_log_buffer.py` | 8 | in-memory log ring buffer behavior |
| `tests/unit/test_log_messages.py` | 16 | humanized log messages per event type |
| `tests/unit/test_models.py` | 3 | model defaults/constraints |
| `tests/unit/letterboxd/test_client.py` | 5 | offline kill-switch, 403 no-retry, 5xx retry+backoff, rate-limit spacing |
| `tests/unit/letterboxd/test_film_page.py` | 10 | film-page parser (tmdb id/type, title/year, ratings) |
| `tests/unit/letterboxd/test_films.py` | 4 | `/films/` (watched) page parser |
| `tests/unit/letterboxd/test_lists.py` | 9 | lists index, list items, pagination parsers |
| `tests/unit/letterboxd/test_rss.py` | 5 | RSS feed parser |
| `tests/integration/test_audit.py` | 4 | `scrape_runs` audit wrapper: success/error rows, orphan-RUNNING marking |
| `tests/integration/test_custom_lists_polymorphic.py` | 12 | custom-list-as-source algebra, cycle detection, PUT partial-payload safety |
| `tests/integration/test_film_resolver.py` | 2 | TMDB-remap handling: slug tombstone + imdb_id yielding |
| `tests/integration/test_radarr_routing.py` | 12 | Radarr routes: payloads, all 404 cases, reserved usernames, ETag/304 |
| `tests/integration/test_rotation.py` | 24 | custom-list pool/sort/rotation/snapshot — biggest single area |
| `tests/integration/test_scheduler.py` | 3 | `sync_jobs` registers expected job ids; interval overrides reschedule |
| `tests/integration/test_scrape_anti_flap.py` | 5 | anti-flap removal rules (watched, films-page backstop, counter threshold) |
| `tests/integration/test_scrape_concurrency.py` | 1 | concurrent RSS + films-backstop without "database is locked" |
| `tests/integration/test_scrape_discovery.py` | 2 | list discovery from a user's lists index |
| `tests/integration/test_scrape_initial_run.py` | 5 | `validate_username` (incl. reserved), watchlist-row bootstrap idempotency |
| `tests/integration/test_scrape_lists.py` | 3 | list scrape sync |
| `tests/integration/test_scrape_rss.py` | 2 | RSS watcher ingestion |
| `tests/integration/test_scrape_watchlist.py` | 3 | watchlist full/incremental sync end-to-end into DB rows |
| `tests/integration/test_ui_smoke.py` | 9 | JSON API surface (`/api/v1/*`) via TestClient + legacy-route 404s |

### Fixture and conftest infrastructure

- **`tests/conftest.py` `db_url`** (tests/conftest.py:21-32): per-test **file-based SQLite in
  pytest `tmp_path`** (never `:memory:`). Sets env `DATABASE_URL`, `LETTERBOXD_OFFLINE=true`,
  `LOG_LEVEL=warning`, clears the `get_settings` lru_cache, then runs the **real Alembic chain**
  (`command.upgrade(cfg, "head")`). Every DB test exercises all migrations from empty — this is
  the suite's main time cost and also its migration safety net.
- **`engine`/`factory`/`session`** (tests/conftest.py:35-52): wrap the real `init_engine`, so the
  production WAL/busy_timeout/FK pragmas (src/watchlistarr/db.py:21-30) are active in tests.
- **`app`** (tests/conftest.py:55-59): `create_app()`. Always use it as
  `with TestClient(app) as client:` — the context manager runs the full lifespan (second alembic
  upgrade + scheduler start, src/watchlistarr/main.py).
- **`tests/integration/conftest.py`**: `fixture_text(name)` reads `tests/fixtures/*` (:14-15);
  `letterboxd_settings` builds `Settings(letterboxd_offline=False, ...)` (:18-20);
  `letterboxd_client` is a **real `LetterboxdClient` with `min_interval_seconds=0`** (:23-29) —
  rate limiting disabled for speed, HTTP intercepted by respx.
- **`tests/unit/letterboxd/conftest.py`**: 8 named fixtures, one per file in `tests/fixtures/`
  (8 files as of 2026-07 — `ls tests/fixtures/`; the what-each-is-a-specimen-of inventory table
  lives in `letterboxd-scraping-reference`).
- **Offline kill-switch (belt and braces)**: the `db_url` fixture exports
  `LETTERBOXD_OFFLINE=true`, and `LetterboxdClient.get` hard-raises `LetterboxdOfflineError` when
  set (src/watchlistarr/services/letterboxd/client.py:64-65). Any unmocked scrape in a DB test
  fails loudly instead of hitting the real site. **Tests require zero network.**

### HTTP mocking, async, markers

- **respx** (pyproject.toml:33) is the only HTTP mock, used across 8 test files. Known anomaly:
  `tests/integration/test_scrape_concurrency.py:45` declares an inert `pass_through()` route for
  the bare base URL — no request targets it; flag it if a future test ever GETs `/`.
- **pytest-asyncio `asyncio_mode = "auto"`** (pyproject.toml:76): plain `async def test_` is
  collected without markers.
- **`addopts = "-ra --strict-markers --strict-config"`** (pyproject.toml:78): any new marker must
  be declared in `pyproject.toml` `markers` or collection fails.
- **The `slow` marker is declared but dead** (pyproject.toml:79): zero tests use
  `@pytest.mark.slow`, and nothing passes `-m "not slow"` anywhere. CI always runs the full suite.

## 3. Coverage reality

**No coverage threshold is enforced anywhere.** CI collects it (`--cov=src/watchlistarr
--cov-report=term`, ci.yml:44) but there is no `--cov-fail-under` and no `fail_under` in
`[tool.coverage.report]` (pyproject.toml:85-90) — coverage is informational only.
`.claude/tech-stack.md:194` ("parsers ≥ 90%, orchestration ≥ 70%") is an aspiration, not a gate.

Untested modules (dated snapshot, 2026-07, v1.5.2 — verified by grepping test imports):

| Module | Status |
|---|---|
| `src/watchlistarr/services/onboarding.py` | never imported by tests (initial-run orchestration; only inner piece `initial_run.validate_username` is tested) |
| `src/watchlistarr/services/scrape/imdb_backfill.py` | zero tests (only reachable via `scripts/backfill_imdb.py`) |
| `src/watchlistarr/services/scrape/rating_backfill.py` | zero tests (only via `scripts/backfill_ratings.py`) |
| `src/watchlistarr/routes/api/admin.py` | zero tests (`/admin/refresh/{job_id}`, `/admin/scheduler/sync`) |
| `src/watchlistarr/services/scrape/films_backstop.py` | only incidental coverage via `test_scrape_concurrency.py` |
| `config.py` `_parse_duration`, `logging.py` `buffer_capture_processor` | no dedicated tests (buffer shape asserted indirectly via `/api/v1/activity`) |

Re-verify instead of trusting the snapshot — authoritative:

```bash
uv run pytest --cov=src/watchlistarr --cov-report=term-missing
```

Fast name-based heuristic (module never referenced by any test — imprecise, but no test run):

```bash
for f in $(find src/watchlistarr -name '*.py' ! -name '__init__.py'); do \
  mod=$(echo "$f" | sed 's|^src/||; s|\.py$||; s|/|.|g'); \
  grep -rq "$mod" tests/ || echo "never referenced by tests: $mod"; done
```

## 4. scripts/smoke.py — anatomy of the only end-to-end net

443 lines (as of 2026-07, v1.5.2). Run: `uv run python scripts/smoke.py`. Prints
`SMOKE OK`/`SMOKE FAIL`, exit 0/1. It is CI step 5 and the only check that boots the app as a
real process. Steps:

1. **Temp resources** (smoke.py:386-390): `TemporaryDirectory` + `sqlite+aiosqlite:///<tmp>/smoke.db`
   + a free localhost port (`_free_port`, :32-35).
2. **Env** (:392-396): `DATABASE_URL`, `LETTERBOXD_OFFLINE=true`, `LOG_LEVEL=warning`, `HTTP_PORT`.
3. **Migrations from a truly empty DB** (:398-403): in-process `alembic upgrade head`
   (temporarily sets `os.environ["DATABASE_URL"]` because `alembic/env.py` reads settings).
4. **Seed** (`_seed`, :51-254) using the real models + real `services.custom_lists.init_items`:
   - Users `alice`, `bob`.
   - 5 films: tmdb 10/20/30/40/50, ratings 3.5/4.2/2.8/4.7/3.9; **film 30 has NO imdb_id**;
     film 50's year is the current year.
   - Lists: alice watchlist (items 10,20,30,50), bob watchlist (30,40), and alice's `private`
     list **disabled** (enabled=False).
   - One `WatchedFilm`: alice watched 10.
   - 4 custom lists: `house` (UNION of both watchlists), `recent` (`year_last_n=1`),
     `top-rated` (RATING_DESC, max_items=3), and `top-of-house` — a **chained** custom list whose
     source is the `house` custom list (RATING_DESC, max_items=2).
5. **Real server** (:407-424): `subprocess.Popen(... uvicorn watchlistarr.main:app ...)` — the
   actual lifespan runs (second alembic upgrade, scheduler start, static mount).
6. **Wait** for `/healthz` up to 15 s (:38-48), then **`_exercise`** (:262-382) asserts:

| Assert group | Exact expectation | Lines |
|---|---|---|
| SPA shell | `/` 200, contains `Watchlistarr` and `id="root"` | :267-270 |
| Static assets | 200 for `/static/styles.css`, `/static/vendor/react.min.js`, `/static/vendor/geist/geist.css` | :272-278 |
| `/api/v1/bootstrap` | keys `users`/`customLists`/`dashboard`; usernames == {alice,bob}; each user `discoveryRunning=False`, `syncingListIds=[]`; each custom list has `snapshotInterval`/`lastSnapshotAt`, `snapshotInterval` starts null | :281-303 |
| `/api/v1/activity?since=0` | `lines`+`latestSeq`; every line has `event`/`fields`/`humanMessage`/`excInfo` | :305-312 |
| `/alice/watchlist/` | exactly 4 items; `id`/`tmdb_id` are ints; `id == tmdb_id`; imdb_id present for 10/20; **key absent (not null) for 30** | :315-326 |
| `/lists/house/` | 5 items, `id == tmdb_id` | :328-332 |
| `/lists/recent/` | exactly `[50]` (year_last_n=1 → current-year only) | :335-341 |
| `/lists/top-rated/` | **exact order** `[40, 20, 50]` (RATING_DESC, max 3) | :346-352 |
| `/lists/top-of-house/` | **exact order** `[40, 20]` (chained source, top-2 by rating) | :358-364 |
| 404s | `/nobody/watchlist/` (unknown user), `/alice/private/` (disabled list) | :366-371 |
| ETag | second GET with `If-None-Match` → 304 | :374-377 |
| Legacy routes dead | `/users`, `/lists-view`, `/custom-lists`, `/activity` all 404 | :380-382 |

7. **Teardown** (:433-439): always terminate/kill the uvicorn child.

**What smoke catches that pytest cannot**: import errors at real-process boot, the lifespan
alembic-upgrade path, migration chain from empty into a *served* state, static assets actually on
disk, exact serialized JSON bytes (key omission vs `null`), HTTP caching headers, and full
composition seed → `init_items` → serve.

## 5. Smoke update triggers — house law

Per `.claude/rules.md:16,18`: if you rename a model, change DB schema, alter an HTTP route, or
change JSON shape, **update `scripts/smoke.py` in the same commit**. Concretely:

| You changed | Update in the SAME commit |
|---|---|
| Model rename / new-removed column / new migration | `_seed` imports and field names (smoke.py:51-254); smoke run proves the chain-from-empty still serves |
| Added or renamed an HTTP route | corresponding smoke assert in `_exercise` |
| **Removed** an HTTP route | add it to the dead-route 404 asserts in **both** `scripts/smoke.py:380-382` and `tests/integration/test_ui_smoke.py:124-127` — removed routes stay asserted dead |
| JSON shape of `/api/v1/bootstrap` or `/api/v1/activity` | schema asserts smoke.py:281-312 + `test_ui_smoke.py` |
| Radarr payload shape / URL scheme / 404 semantics | **breaking change** — gate through `watchlistarr-change-control` first; then byte-level asserts smoke.py:315-377 + `test_radarr_routing.py` |
| Sort/filter/rotation semantics of custom lists | expected orders `[40,20,50]`, `[40,20]`, `[50]` and counts (smoke.py:328-364) + `test_rotation.py` |
| Static asset paths / SPA shell | asset asserts smoke.py:267-278 |

## 6. How to add tests

Three patterns; copy the exemplar.

1. **Parser test (fixture-driven, sync, no DB)** — exemplar
   `tests/unit/letterboxd/test_lists.py:10-22`.
   Save a **minimal** HTML/XML specimen in `tests/fixtures/` (trim a real Letterboxd capture to
   the structural skeleton; current specimens run 279 B – 3 KB, keep new ones in that range).
   Add a named fixture in `tests/unit/letterboxd/conftest.py` (pattern at :10-16). Assert parsed
   values, plus an empty-HTML case (parsers must fail loudly or return `[]`, never guess —
   `.claude/rules.md:81`). Fixture provenance and selector tables: `letterboxd-scraping-reference`.
2. **Scrape-orchestration test (respx + DB)** — exemplar
   `tests/integration/test_scrape_watchlist.py:49-78`.
   Decorate with `@respx.mock`; mock exact URLs
   (`respx.get("https://letterboxd.com/alice/watchlist/").mock(return_value=httpx.Response(200,
   text=fixture_text("watchlist_p1.html")))`); stub per-film pages with inline minimal HTML
   (`_stub_film_page` helper, :21-30); use the `letterboxd_client` + `factory`/`session`
   fixtures; run the real sync function; assert resulting DB rows. Any URL you forget to mock
   raises `LetterboxdOfflineError` — that is the kill-switch working, not a bug.
3. **DB/service integration test (no HTTP)** — exemplar `tests/integration/test_rotation.py`
   (seed helpers at top). Take `session`/`factory` from the root conftest (real migrated SQLite),
   seed models directly, call service functions, assert. For HTTP-level asserts, take `app` and
   wrap in `with TestClient(app)` (exemplar: `tests/integration/test_radarr_routing.py`).

Rules that apply to every new test: `async def test_` needs no marker (asyncio auto mode); new
markers must be declared in `pyproject.toml` or `--strict-markers` breaks collection; mirror the
`src/watchlistarr/` structure; never touch the real network.

## 7. Validation gates for the Radarr payload

The served Radarr JSON — item shape, URL scheme, 404 semantics — is sacred: any change is a
breaking change that must be gated through `watchlistarr-change-control` and land with updated
smoke asserts (§5) and `test_radarr_routing.py` in the same commit. The contract itself
(canonical item formula, StevenLuParser behavior, ETag) lives in `radarr-integration-reference`.

## 8. What CI does NOT catch — honest gaps

| Gap | Detail | Mitigation |
|---|---|---|
| Changes to `ci.yml` itself | The 5 steps do not validate the workflow file; a bad action pin fails only remotely (`.claude/rules.md:19`) | Verify refs exist (`git ls-remote --tags <action-repo>`); after pushing to `dev`, wait for the remote run to be green before merging to `main` |
| `scripts/` lint/format | CI ruff scope is `src tests` only (ci.yml:35,38) | The local house command (§1) is the only gate — never skip it |
| Type errors in `tests/` and `scripts/` | mypy runs on `src` only, everywhere | none today (open candidate) |
| Docker image build on dev branches | `docker` job runs only on push to `main` or `v*` tags (ci.yml:53); a Dockerfile break surfaces at merge/release | the standard local QC rebuild (`docker compose -f docker-compose.dev.yml up -d --build`) exercises the build — see `watchlistarr-run-and-operate` |
| Real Letterboxd HTML drift | Fixtures freeze the HTML; a green suite proves parsers match the *specimens*, not today's live site | live selector checks belong to `letterboxd-scraping-reference` / `watchlistarr-debugging-playbook` |
| Coverage regressions | No threshold anywhere (§3); a PR can delete tests and stay green | read the CI coverage report when reviewing |
| Backfill scripts | `scripts/backfill_imdb.py` / `backfill_ratings.py` and their service modules have zero tests and are not smoke-covered | manual runs only; see `watchlistarr-diagnostics-and-tooling` |

## Provenance and maintenance

All facts verified against the repo on 2026-07-02 (v1.5.2, HEAD `4439c17`). Re-verify before
trusting any of them:

| Fact | Re-verify with |
|---|---|
| The 5 CI steps + scopes | `grep -n "run:" .github/workflows/ci.yml` |
| Docker job gate (main/tags only) | `grep -n "if:" .github/workflows/ci.yml` |
| Local house command | `sed -n '21,29p' .claude/rules.md` |
| Smoke-in-same-commit + 404-mirror rules | `sed -n '13,19p' .claude/rules.md` |
| pytest config, asyncio mode, markers | `sed -n '75,90p' pyproject.toml` |
| No coverage threshold | `grep -rn "fail_under\|fail-under" pyproject.toml .github/` → expect empty |
| Test counts per file | `grep -rc "def test_" tests/ \| grep -v ":0$" \| sort -t: -k2 -nr` |
| `slow` marker still unused | `grep -rn "mark.slow" tests/ src/ scripts/` → expect empty |
| Offline kill-switch | `grep -ni "letterboxd_offline" src/watchlistarr/services/letterboxd/client.py tests/conftest.py` (case-insensitive: `tests/conftest.py:26` uses the uppercase env literal) |
| Smoke assert inventory | `grep -n "_assert" scripts/smoke.py` |
| Legacy-404 mirror in both places | `grep -n "lists-view" scripts/smoke.py tests/integration/test_ui_smoke.py` |
| Untested-modules snapshot | heuristic command in §3, or the authoritative `--cov-report=term-missing` run |
| Fixture inventory and sizes | `ls -la tests/fixtures/` |
| respx usage spread | `grep -rln "respx" tests/` |
