---
name: watchlistarr-proof-and-analysis-toolkit
description: Recipes to PROVE claims about watchlistarr with evidence — reproduce a scraping bug offline with trimmed HTML fixtures, build a respx repro of a sync/orchestration bug, prove or disprove a SQLite lock-contention hypothesis, verify an Alembic migration is safe before shipping, bisect a regression with git + pytest, run EXPLAIN QUERY PLAN on the Radarr serving queries, and the predict-then-measure protocol for numeric claims. Use when you need a reproduction, a verification method, or hard evidence before/after a fix. NOT for symptom-to-fix decision trees (use `watchlistarr-debugging-playbook`), NOT for full historical incident stories (use `watchlistarr-failure-archaeology`), NOT for ready-made runnable diagnostic scripts or live-instance probes (use `watchlistarr-diagnostics-and-tooling`), NOT for the evidence bar / idea lifecycle rules themselves (use `watchlistarr-research-methodology`).
---

# watchlistarr proof and analysis toolkit

Seven recipes for turning "I think X is broken/safe/fast" into evidence. Each recipe: when you
need it, exact steps from repo root, and a worked example from this repo's history (method focus;
full incident stories live in `watchlistarr-failure-archaeology`). All commands assume a checkout
with `uv sync` done. Anchors verified against v1.5.2 (HEAD `4439c17`, 2026-07).

## When to use

- You have a suspected parser/scraper bug and need it failing in a test before you touch code.
- You need to prove a sync-pipeline bug end-to-end (HTTP sequence in, DB state out) without
  hitting live Letterboxd.
- Someone (including you) claims "it's lock contention" / "this query is slow" / "this migration
  is safe" and you need to confirm or kill the claim.
- You know behavior changed but not which commit changed it.
- You are about to state a number (latency, request count, payload size) in a commit, doc, or gate.

## When NOT to use

- You have a live symptom and no hypothesis yet → `watchlistarr-debugging-playbook` (decision trees).
- You want the story of a past incident → `watchlistarr-failure-archaeology`.
- You want a script that inspects a running instance → `watchlistarr-diagnostics-and-tooling`.
- You want Letterboxd selector/URL tables → `letterboxd-scraping-reference`; Radarr contract
  details → `radarr-integration-reference`.
- You are deciding whether the evidence is *enough* to ship → `watchlistarr-research-methodology`
  and `watchlistarr-change-control`.

## Recipe 1 — Reproduce a scraping bug offline with fixtures

**Use when** a parser mis-reads Letterboxd HTML (wrong count, missed items, wrong pagination) and
you need a deterministic, network-free failing test.

House rule: fixtures are real Letterboxd captures **trimmed to ≤ 5 KB each** (`.claude/tech-stack.md:190`).
Current fixtures are all under 3.1 KB (`ls -la tests/fixtures/`).

1. Capture a specimen once, with the honest User-Agent (scraping etiquette, `.claude/rules.md:74-82`):
   ```bash
   curl -s -A "watchlistarr/1.5.2 (+https://github.com/maxlainz/watchlistarr)" \
     "https://letterboxd.com/<user>/list/<slug>/" -o "$(mktemp -d)/raw.html"
   ```
   If the structure is already known, prefer a hand-built minimal specimen (see the inline
   `_stub_film_page` HTML in `tests/integration/test_scrape_lists.py:17-27`) — no network at all.
2. Trim to only what the selector under test needs. The selectors (ground truth, see
   `letterboxd-scraping-reference` for the full table): list items =
   `div.react-component[data-item-slug]` (`src/watchlistarr/services/letterboxd/lists.py:45`),
   pagination = `div.pagination` anchors with `/page/N/` hrefs (`lists.py:54-65`), film identity =
   `<body data-tmdb-type data-tmdb-id>` + `og:title` meta
   (`src/watchlistarr/services/letterboxd/film_page.py:14-41`). Keep the bug-triggering quirk intact.
3. Drop the file into `tests/fixtures/<name>.html` and add a loader fixture following the existing
   pattern in `tests/unit/letterboxd/conftest.py:14-51` (one `pytest.fixture` per file).
4. Write a parser test: input = fixture string, output = typed struct, no DB, no network.
   Exemplary model: `tests/unit/letterboxd/test_lists.py:32-37` (`test_parse_total_pages_with_block`
   asserts `parse_total_pages(pagination_block_html) == 23`; its sibling asserts the no-pagination
   case returns 1).
5. Run just it:
   ```bash
   uv run pytest -q tests/unit/letterboxd/test_lists.py -k total_pages
   ```
   Expect a failure that names the wrong value. If it passes, your fixture does not contain the
   quirk — re-trim from the raw capture.

**Worked example — pinning the `/by/added-earliest/` incremental trick.** Incremental list syncs
fetch page 1 plus the *last* page of the `by/added-earliest` sort (newest additions live at the
end of that sort), instead of walking every page (`src/watchlistarr/services/scrape/lists.py:108-135`,
URL builder `lists.py:21-27`). Two tiny fixtures pin this: `pagination_block.html` (692 bytes)
proves `parse_total_pages` reads "23" out of a pagination block (`test_lists.py:32-33`), and
`watchlist_p1.html` (1.9 KB) proves item extraction. The integration test
`tests/integration/test_scrape_lists.py:76-100` then mocks page 1 with the pagination fixture and
asserts the scraper requests exactly `https://letterboxd.com/alice/list/favs/by/added-earliest/page/23/`
— if either the selector or the URL scheme drifts, one of these two layers fails and names which.

## Recipe 2 — Build a respx repro of an orchestration bug

**Use when** the bug is not in a parser but in the *pipeline*: what a sync writes to the DB given
a known sequence of HTTP responses. respx is the only HTTP mock in the suite (`pyproject.toml`
dev group); any unmocked request fails loudly because the test fixtures also set
`LETTERBOXD_OFFLINE=true` (`tests/conftest.py:26`) and the client hard-raises on it
(`src/watchlistarr/services/letterboxd/client.py:63-65`).

**Step 1 — enumerate the exact URL sequence** the sync makes (read, don't guess). For a raw list
owned by `alice` with slug `favs` (from `src/watchlistarr/services/scrape/lists.py`):

| Sync | Order | URL | Condition |
|---|---|---|---|
| full | 1 | `/alice/list/favs/` | always (`lists.py:44-57`) |
| full | 2..N | `/alice/list/favs/page/{n}/` | while `n <= parse_total_pages(page1)` |
| full | +1 per slug | `/film/{slug}/` | slug not cached with imdb_id AND rating (`film_resolver.py:106-116`) |
| full | 0 or 1 | `/alice/films/` | unexplained disappearances only; fetched BEFORE the write session (`anti_flap.py:50-74`) |
| incremental | 1 | `/alice/list/favs/` | always (`lists.py:118`) |
| incremental | 2 | `/alice/list/favs/by/added-earliest/page/{total}/` | only if `total_pages > 1` (`lists.py:121-124`) |
| incremental | +1 per new slug | `/film/{slug}/` | as above; never removes, `reassign_positions=False` (`lists.py:143`) |

Watchlists are the same shape with `/alice/watchlist/` paths and **page-1-only** incrementals, no
added-earliest (`src/watchlistarr/services/scrape/watchlist.py:22-23,180-190`). All URLs resolve
against `BASE_URL = "https://letterboxd.com"` (`client.py:14`).

**Step 2 — write the repro** using `tests/integration/test_scrape_lists.py` as the structural
template: seed user+list rows, `respx.get(<absolute URL>).mock(return_value=httpx.Response(200, text=...))`
for every URL in the table (fixture files via `fixture_text()` from
`tests/integration/conftest.py:14`, film pages via an inline `_stub_film_page` helper), call the
real `sync_list_full`/`sync_list_incremental` with the `factory` and `letterboxd_client` fixtures
(rate limit is 0 in tests, `tests/integration/conftest.py:24`), then **assert the DB end-state**
by selecting `ListItem` rows. For pure reconciliation logic you can skip HTTP entirely and drive
`reconcile_full_scrape` on a session — that is exactly what
`tests/integration/test_scrape_anti_flap.py` does (the anti-flap canonical formula lives in
`watchlistarr-architecture-contract`).

**Step 3 — run it**: `uv run pytest -q tests/integration/test_scrape_lists.py -k <your_test>`.
An unmocked URL raises instead of silently hitting the network — that error *is* your sequence
enumeration being corrected.

**Worked example — how INC-1 (TMDB remap, fixed `2be042c` + `a6b8dca`, v1.5.1) would have been
reproduced before the fix.** Letterboxd remapped a film page to a different TMDB entry and every
subsequent full sync crashed on UNIQUE constraints — details in `watchlistarr-failure-archaeology`.
The repro is one test: seed `Film(tmdb_id=200, letterboxd_slug="foo", title="Foo", year=2020)` plus
its `ListItem`; mock `/alice/list/favs/` returning one item with slug `foo`; mock `/film/foo/` with
a stub page carrying the **same og:title "Foo (2020)" but `data-tmdb-id="999"`**; run
`sync_list_full`. On the pre-fix code path, `resolve_films` inserts tmdb 999 with slug `foo` →
`IntegrityError: UNIQUE constraint failed: films.letterboxd_slug` — permanent, every run. On fixed
code, the old row is tombstoned to `foo--superseded-200` (`film_resolver.py:37-54`), a competing
imdb_id is yielded (`film_resolver.py:57-72`), and the stale item goes through the removal counter
— pinned by `tests/integration/test_scrape_anti_flap.py:58-86`.

## Recipe 3 — Prove or disprove a lock-contention hypothesis

**Use when** you see `sqlite3.OperationalError: database is locked` or suspect a write
transaction is being held across slow work.

1. **Confirm the baseline pragmas are active.** Every SQLite connection gets
   `journal_mode=WAL`, `busy_timeout=10000`, `synchronous=NORMAL`, `foreign_keys=ON` at connect
   (`src/watchlistarr/db.py:21-30`, wired via `init_engine` `db.py:33-42`). Verify on the real DB:
   ```bash
   sqlite3 data/watchlistarr.db "PRAGMA journal_mode;"   # expect: wal
   ls data/                                              # expect -wal and -shm sidecar files
   ```
   `busy_timeout` is per-connection (set by the app, not persisted) — a bare `sqlite3` shell does
   NOT have it; set `PRAGMA busy_timeout=10000;` before poking a live DB or you become the
   contention you are measuring.
2. **Interpret the symptom.** WAL allows many readers + exactly one writer. "database is locked"
   after ~10 s means one writer held the write lock longer than `busy_timeout` while another
   writer waited. The question is never "is SQLite broken", it is "who holds a write transaction
   open, and what slow thing runs inside it".
3. **Spot HTTP-inside-transaction in code review.** The invariant (fetch-first / write-last: no
   HTTP inside a SQLite write transaction) is owned by `watchlistarr-architecture-contract`. The
   greppable smell — a client call textually close after a session opens:
   ```bash
   rg -nU --multiline-dotall 'async with factory\(\) as session:.{0,800}?await client\.' src/watchlistarr/
   ```
   Treat hits as **candidates, not verdicts**: the pattern also matches the correct
   read-session → close → fetch shape (it fires today on `film_resolver.py:96` followed by the
   fetch loop at `:114-117`, which is fine — the session block closed at `:101`). For each hit,
   check indentation: is `await client.` *inside* the `async with` block? Complement with the
   exhaustive list of call sites: `rg -n 'await client\.' src/watchlistarr/services/` (11 hits as
   of v1.5.2) and confirm none sits inside a session block.
4. **Prove concurrency safety dynamically**: the regression test
   `tests/integration/test_scrape_concurrency.py:29-64` runs two writing scrapers under
   `asyncio.gather` against one file-backed DB. Extend it (same shape, your two jobs) to prove a
   new pipeline is lock-safe:
   ```bash
   uv run pytest -q tests/integration/test_scrape_concurrency.py
   ```

**Worked example — the `b7a44d2` refactor (v1.0.2).** The initial-run scraper held one write
transaction across all HTTP fetches (~25 min for a 642-film watchlist), so any concurrent writer
blew the 10 s timeout — see `watchlistarr-failure-archaeology` for the full story. The structural
proof of what changed: `git show --stat b7a44d2` — 20 files, +716/−402, touching all five scrapers
(`rss_watcher`, `films_backstop`, `watchlist`, `lists`, `discovery`) plus `film_resolver.py`
(single `resolve_film` → batch `resolve_films` returning flat `ResolvedFilm` dataclasses safe
across session boundaries) and adding `test_scrape_concurrency.py` as the permanent guard. That
stat line is the shape of a real fix; the earlier `321b8d1` (WAL + commit-every-10) was the
band-aid.

## Recipe 4 — Verify a migration is safe before shipping

**Use when** you added/edited anything under `alembic/versions/` or changed
`src/watchlistarr/models/`.

Background you get for free: **pytest applies the real migration chain per test** — the `db_url`
fixture runs `command.upgrade(cfg, "head")` against a fresh file DB for every test that touches
the DB (`tests/conftest.py:21-32`). A broken chain fails the whole suite, not just migration tests.

1. **Run the chain on an empty DB** (env var beats `.env`; `alembic/env.py:22-23` reads
   `DATABASE_URL` via `get_settings()`):
   ```bash
   TMP=$(mktemp -d)
   DATABASE_URL="sqlite+aiosqlite:///$TMP/fresh.db" uv run alembic upgrade head
   ```
   Expected: exits 0. Known quirk: the chain creates then drops the 0007 cooldown columns
   (0007/0008 are a dead add-then-drop pair kept forward-only) — not a bug, do not "clean it up".
2. **Autogenerate diff-check** — after upgrading, autogenerate against the same DB; models vs
   schema must produce an **empty** migration (`alembic/env.py:19` sets
   `target_metadata = Base.metadata`, so autogenerate works):
   ```bash
   DATABASE_URL="sqlite+aiosqlite:///$TMP/fresh.db" uv run alembic revision --autogenerate -m "drift check"
   ```
   Open the newly created file in `alembic/versions/`: `upgrade()` must contain only `pass`.
   Anything else = your models and your migration disagree — fix the migration, not the models.
   **Delete the drift-check file afterward; never commit it.** Caveat: autogenerate can emit false
   positives (server defaults, `Interval` rendering on SQLite) — inspect before concluding drift.
3. **Test with seeded data via the smoke path.** `scripts/smoke.py` runs the full chain on an
   empty temp DB, seeds 2 users / 5 films / 3 lists / 4 custom lists through the real models
   (`scripts/smoke.py:51` `_seed`, invoked at `:398-405`), boots a real uvicorn, and asserts the
   served JSON byte-level:
   ```bash
   uv run python scripts/smoke.py    # expect: SMOKE OK
   ```
   This is the CI step that catches "migration passes but serving breaks". If your migration
   changes schema, `.claude/rules.md:16` requires updating smoke.py in the same commit —
   enforcement details in `watchlistarr-change-control`.
4. **Check the SQLite-masks-enums trap.** SQLite stores `sa.Enum` as VARCHAR with no check
   constraint, so an enum value missing from the migration DDL passes every SQLite test and every
   smoke run, then breaks Postgres. For any migration touching an `sa.Enum`, diff the DDL values
   against the enum class in `src/watchlistarr/models/enums.py` by eye — no tool does it for you:
   ```bash
   rg -n "sa.Enum\(" alembic/versions/<your_migration>.py
   rg -n "class .*Enum|= \"" src/watchlistarr/models/enums.py
   ```
5. **Check `downgrade()` exists and is honest** — a documented no-op (like 0006's, where Postgres
   cannot drop enum values) beats a lying one.

**Worked example — migration 0003's missing `rating_desc` (fixed `d8ae10c`, migration 0006,
v1.2.3).** 0003 created `sort_order_enum` as `('letterboxd', 'random', 'reverse')`
(`alembic/versions/0003_custom_lists_multisource.py:47-51`) while the model also declared
`RATING_DESC`; SQLite's VARCHAR enums masked it through every test, and only Postgres deployments
would crash — full story in `watchlistarr-failure-archaeology`. The method lesson: step 4 above
(a 30-second eyeball diff of DDL vs enum class) is the *only* check that would have caught it,
because steps 1–3 all pass on SQLite. The fix, 0006, is a Postgres-only
`ALTER TYPE sort_order_enum ADD VALUE IF NOT EXISTS 'rating_desc'`
(`alembic/versions/0006_sort_order_rating_desc.py:30-37`) with a documented no-op downgrade.

## Recipe 5 — Bisect discipline adapted to this repo

**Use when** an invariant used to hold and now doesn't, and `git log -S` didn't find the culprit.

0. **Try pickaxe first** — with only 97 commits (as of 2026-07, v1.5.2), a keyword search usually
   beats bisect: `git log -S "reassign_positions" --oneline` lands on `25aa6e5` instantly.
1. **Fetch tags** — clones of this repo often lack them (`git tag` may print nothing; the 13
   annotated tags v1.0.0–v1.5.2 live on origin):
   ```bash
   git fetch --tags origin
   ```
2. **Pick a predicate**: a single pytest node that encodes the invariant, run as
   `uv run pytest -q <nodeid>`. `uv run` auto-syncs the venv from that revision's `uv.lock` at
   every bisect step — correct but slow; if a historical lockfile fails to sync, `git bisect skip`.
3. **Run it**:
   ```bash
   git bisect start
   git bisect bad HEAD
   git bisect good vX.Y.Z    # a tag where the predicate passes
   git bisect run uv run pytest -q tests/integration/test_rotation.py::test_rotate_leaves_positions_unique_and_consecutive
   git bisect reset          # always; bisect moves HEAD
   ```
4. **Caveats specific to this repo**:
   - If the regression test postdates the bug, keep a self-contained repro test *outside* the work
     tree (e.g. your scratchpad) and use
     `git bisect run sh -c 'uv run pytest -q /path/to/repro_test.py'`. Repro tests that lean on
     `tests/conftest.py` fixtures may break on old revisions where those fixtures differed
     (`b7a44d2` reshaped them) — prefer tests that only import stable modules, or skip those steps.
   - To locate a *fix* rather than a break, invert the predicate:
     `git bisect run sh -c '! uv run pytest -q <nodeid>'`.
   - Bisect needs a clean tree; stash first. Never bisect on `main` state you intend to push —
     branch discipline is `watchlistarr-change-control`'s.

**Worked example — the position-corruption cluster (v1.2.3).** Symptom: the order served to Radarr
shuffled over time with no error (positions are not UNIQUE in the DB, so nothing crashed) — full
story in `watchlistarr-failure-archaeology`. The invariant tests that now pin it:
`tests/integration/test_rotation.py::test_rotate_leaves_positions_unique_and_consecutive`
(`test_rotation.py:471`, guards the `72b2f10` rotate-duplication fix) and
`tests/integration/test_scrape_lists.py:104-141` (guards the `25aa6e5` incremental-corruption fix
— seed positions `[50,51,52]`, run an incremental, positions must persist). Since these bugs
existed from the feature's birth, bisect for "first bad" had no good endpoint — the working method
was step 0 (pickaxe on `position`) plus the inverted predicate to confirm exactly which commit made
the invariant test pass: `git bisect start; git bisect bad v1.2.2; git bisect good v1.2.3` with
`sh -c '! uv run pytest -q <repro>'` isolates `25aa6e5` between those tags.

## Recipe 6 — Query-plan and perf analysis of the serving path

**Use when** someone proposes an index, or a Radarr endpoint feels slow, and you need the plan,
not vibes.

1. **Know the real queries.** The Radarr serving SQL is static and lives in two functions:
   - Raw lists: `src/watchlistarr/services/radarr.py:17-29` —
     `SELECT list_items.tmdb_id, films.title, films.imdb_id FROM list_items JOIN films ON
     list_items.tmdb_id = films.tmdb_id WHERE list_items.list_id = ? ORDER BY
     list_items.position, list_items.tmdb_id` (called from `routes/api/radarr.py:54,81`).
   - Custom lists: `radarr.py:32-56` — same join over `custom_list_items`, ordered by `position`
     (or by `films.letterboxd_avg_rating DESC` when `sort_order=RATING_DESC` outside snapshot
     mode), `LIMIT max_items` when set (called from `routes/api/radarr.py:39`).
   The recalculation-side queries are in `src/watchlistarr/services/custom_lists.py`
   (`_apply_filters` `:163`, `_choose_from_pool` `:271-298`, `eligible_pool` `:301-314`).
2. **Get the compiled SQL from the code** (do this instead of trusting the transcription above
   whenever the code may have moved):
   ```bash
   uv run python - <<'EOF'
   from sqlalchemy import select
   from sqlalchemy.dialects import sqlite
   from watchlistarr.models.films import Film
   from watchlistarr.models.list_items import ListItem
   stmt = (
       select(ListItem.tmdb_id, Film.title, Film.imdb_id)
       .join(Film, ListItem.tmdb_id == Film.tmdb_id)
       .where(ListItem.list_id == 1)
       .order_by(ListItem.position, ListItem.tmdb_id)
   )
   print(stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
   EOF
   ```
3. **Run EXPLAIN QUERY PLAN** on the real DB (host path `./data/watchlistarr.db` under compose):
   ```bash
   sqlite3 data/watchlistarr.db "EXPLAIN QUERY PLAN <paste compiled SQL>;"
   ```
   Read it as: `SEARCH ... USING INDEX` = good; `SCAN <table>` on a table that grows with
   users/films = candidate problem; `USE TEMP B-TREE FOR ORDER BY` = the sort is not
   index-satisfied.
4. **Read the existing indexes before proposing one.** Current inventory (from the migration
   chain; live check: `sqlite3 data/watchlistarr.db "SELECT name, tbl_name FROM sqlite_master
   WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%' ORDER BY tbl_name;"`):

   | Index | Table (columns) | Since |
   |---|---|---|
   | `ix_films_letterboxd_slug` | films (letterboxd_slug) UNIQUE | 0001 |
   | `ix_films_imdb_id` | films (imdb_id) UNIQUE partial, `WHERE imdb_id IS NOT NULL` | 0004 |
   | `ix_users_letterboxd_username` | users (letterboxd_username) UNIQUE | 0001 |
   | `ix_lists_user_id` | lists (user_id) | 0001 |
   | `ix_list_items_list_position` | list_items (list_id, position) | 0001 |
   | `ix_list_items_tmdb` | list_items (tmdb_id) | 0001 |
   | `ix_watched_films_tmdb` | watched_films (tmdb_id) | 0001 |
   | `ix_viewing_logs_tmdb_id` / `ix_viewing_logs_user_id` | viewing_logs | 0001 |
   | `ix_scrape_runs_source_started` / `ix_scrape_runs_target` | scrape_runs | 0001 |
   | `ix_custom_lists_slug` | custom_lists (slug) | 0003 |
   | `ix_custom_list_items_served_since` | custom_list_items (custom_list_id, served_since) | 0003 |
   | `ix_custom_list_sources_custom_list_id` / `_list_id` / `_source_custom_list_id` | custom_list_sources | 0009 |

   Note `ix_list_items_list_position` already covers the raw-list serving query's WHERE + ORDER BY.
5. **An index is justified only when** (a) EQP shows a SCAN or TEMP B-TREE on a serving-path or
   scrape-hot query, (b) at a realistic row count (thousands of films, not the 5-film smoke seed),
   and (c) a before/after measurement shows it matters (Recipe 7). Serving tables here are small;
   most "add an index" instincts fail test (c). Adding one = a migration = Recipe 4 applies.

## Recipe 7 — Predict-then-measure protocol for any numeric claim

Before running any measurement (request counts, sync duration, payload bytes, query timings),
**write your predicted number down first**, then run, then explain any gap larger than 2x before
acting on the result — a number you predicted wrong is a model you don't have yet. The full
worksheet, evidence bar, and the cooldown-revert cautionary tale live in
`watchlistarr-research-methodology`.

## Provenance and maintenance

Everything above was verified by reading the repo at HEAD `4439c17` (v1.5.2, 2026-07). Re-verify
before trusting, in one line each:

| Fact | Re-verify with |
|---|---|
| Fixture inventory and ≤5 KB sizes | `wc -c tests/fixtures/*` and `grep -n "5 KB" .claude/tech-stack.md` |
| Fixture loader pattern | `sed -n '14,51p' tests/unit/letterboxd/conftest.py` |
| Incremental URL trick (`by/added-earliest`) | `grep -n "added-earliest" src/watchlistarr/services/scrape/lists.py tests/integration/test_scrape_lists.py` |
| Full/incremental sync URL sequence | read `src/watchlistarr/services/scrape/lists.py` and `watchlist.py` top to bottom |
| Films-backstop fetch is pre-transaction | `grep -n "adhoc_films_backstop" src/watchlistarr/services/scrape/lists.py src/watchlistarr/services/scrape/anti_flap.py` |
| SQLite pragmas (WAL, busy_timeout) | `grep -n "PRAGMA" src/watchlistarr/db.py` |
| HTTP call sites in services | `rg -n 'await client\.' src/watchlistarr/services/` |
| Concurrency regression test | `grep -n "asyncio.gather" tests/integration/test_scrape_concurrency.py` |
| pytest runs real migration chain per test | `grep -n "command.upgrade" tests/conftest.py` |
| Autogenerate works (target_metadata set) | `grep -n "target_metadata" alembic/env.py` |
| smoke.py seeds then serves | `grep -n "_seed\|command.upgrade" scripts/smoke.py` |
| 0003 enum DDL missing rating_desc, 0006 fix | `grep -n "sort_order_enum" alembic/versions/0003_custom_lists_multisource.py alembic/versions/0006_sort_order_rating_desc.py` |
| Serving SQL shape | `sed -n '17,56p' src/watchlistarr/services/radarr.py` |
| Radarr route paths | `grep -n "@router.get" src/watchlistarr/routes/api/radarr.py` |
| Index inventory | `grep -n "create_index" alembic/versions/*.py` (minus tables dropped in 0003/0009) |
| Position-invariant tests | `grep -n "positions_unique\|preserves_existing_positions" -r tests/integration/` |
| Historical commits cited (`b7a44d2`, `25aa6e5`, `72b2f10`, `2be042c`, `a6b8dca`, `d8ae10c`, `321b8d1`) | `git show --stat <sha>` (read-only) |
| Tags present locally | `git tag` — if empty, `git fetch --tags origin` |

If a command above returns nothing where a hit is promised, the code moved: fix this skill in the
same change, per the doc-update triggers owned by `watchlistarr-docs-and-writing`.
