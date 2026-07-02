---
name: watchlistarr-failure-archaeology
description: Historical incident reference for watchlistarr — every production bug, revert, and rework from git history (2026-05-19 to 2026-06-11), each with symptom, root cause, file-level fix, commit SHAs, shipped version, generalized lesson, and a tripwire to avoid re-creating it. Use when asking "has this happened before?", "why is the code shaped like this?", when reviewing changes that touch films UNIQUE constraints, custom-list positions, scheduler jobs, SQLite transactions, or the Radarr payload, or before proposing scrape throttling, a global settings table, a UI rewrite, or migration-chain cleanup (all fenced-off wrong paths, documented here). NOT for diagnosing a live problem right now — use watchlistarr-debugging-playbook. NOT for planning current work on the four live problem tracks — use watchlistarr-hardening-campaign. NOT for doc errata — use watchlistarr-docs-and-writing.
---

# watchlistarr failure archaeology

The single home of full incident stories for this repo. Other skills cite incidents in at most
two sentences and cross-reference here. Everything below is verified against git as of 2026-07
(HEAD `4439c17`, v1.5.2 + one docs commit). Where a scratch document or a doc of record disagrees
with git, git wins — two such corrections are flagged inline.

## When to use

- A change touches a historically dangerous area: `films.letterboxd_slug` / `films.imdb_id`
  UNIQUE constraints, `custom_list_items.position`, scheduler job wrappers, SQLite write
  transactions, the Radarr JSON payload, `ci.yml` action refs, or the release procedure.
- Someone proposes an idea that smells like a fenced-off wrong path (scrape cooldown, global
  settings table, HTMX return, predefined combined lists, license change).
- You need to explain WHY a defensive oddity exists (slug tombstones, `reassign_positions=False`,
  `_reindex_positions`, orphaned-RUN cleanup at boot, the dead 0007/0008 migration pair).
- You are writing a postmortem or lesson and want the precedent with SHAs.

## When NOT to use

- A live instance is misbehaving now → `watchlistarr-debugging-playbook` (symptom→fix trees).
- You are planning work on anti-bot resilience, zero-flap, first-sync latency, or custom-list
  debt → `watchlistarr-hardening-campaign`.
- You need current invariants and formulas, not their origin → `watchlistarr-architecture-contract`.
- You need the doc-drift errata table → `watchlistarr-docs-and-writing`.

## Project timeline (dates from git)

| Date | Phase | Anchors |
|---|---|---|
| 2026-05-19 | Docs-first: 7 pure-spec commits before any code (Radarr contract, RSS, list scraping, data model, GUI, stack) | `2474c68` … `28b09a5` |
| 2026-05-20 | MVP in one commit (FastAPI + scraper + Radarr API + HTMX GUI + Docker, migration 0001); same day: startup/lock fixes, settings rework, two full UI reworks | `554a808`; `293d4d5`…`72ff656` |
| 2026-05-21 | Release sprint day 1: v1.0.0, v1.0.1, v1.0.2, v1.1.0, v1.2.0 | `a97ebf7` … `8b7d32b` |
| 2026-05-22 | Sprint day 2: v1.2.1, v1.2.2, v1.2.3, v1.3.0 | `628f589` … `991ddbc` |
| 2026-05-23 | Sprint day 3: v1.4.0 (cooldown revert + snapshot), v1.5.0 (polymorphic sources) | `5c4924d`, `2405fd4` |
| 2026-05-24 → 2026-06-10 | 19-day gap, zero commits | — |
| 2026-06-11 | Robustness audit (6 fixes → v1.5.1), repo goes public, GPL + README + CI → v1.5.2, final process-docs commit = HEAD | `3b90044`, `f7f28c6`, `4439c17` |

97 commits total, 76 non-merge as of the audited anchor `4439c17` (before the skills commits);
13 annotated tags v1.0.0–v1.5.2 on origin (as of 2026-07). Recount:
`git rev-list --count 4439c17` / `git rev-list --count --no-merges 4439c17` — counting `HEAD`
includes later docs/skills commits and will exceed 97.

## Incident index

| ID | Name | Shipped in |
|---|---|---|
| INC-1 | The TMDB remap that killed every sync | v1.5.1 |
| INC-2 | "database is locked" — HTTP inside a write transaction | v1.0.0 (band-aid), v1.0.2 (fix) |
| INC-3 | Radarr "No results returned" — the imdb_id blind spot | v1.0.1 |
| INC-4 | Scheduler blind spots — unaudited jobs and blocking shutdown | v1.2.3, v1.5.1 |
| INC-5 | Custom-list ordering rot (5-bug cluster) | v1.2.0 → v1.5.1 |
| INC-6 | The cooldown revert (33 minutes) | v1.4.0 (add+remove together) |
| INC-7 | The latent Postgres enum bug SQLite hid | v1.2.3 |
| INC-8 | The uv.lock release pitfall (bitten twice) | v1.1.0, v1.2.2 |
| INC-9 | Add-user hung the browser; logs vanished after Alembic | pre-v1.0.0 |
| INC-10 | Naive/aware datetime TypeError every rotation tick | v1.2.1 |
| INC-11 | Disabled lists still served to Radarr | v1.5.1 |
| INC-12 | `lists` was never reserved as a username | v1.5.1 |
| INC-13 | CI broke on a floating action tag | v1.5.2 |

## Incidents

### INC-1 — The TMDB remap that killed every sync

- **Symptom:** every full sync of an affected list failed forever with an IntegrityError; the
  list froze at its last good state while other lists kept syncing.
- **Root cause:** Letterboxd remapped a film page (same slug) to a different TMDB entry. Two
  independent crash paths: (a) the anti-flap "rename" branch reassigned the new film's slug to
  the old row, violating `UNIQUE(letterboxd_slug)`; (b) in the resolver, inserting the new film
  collided with `UNIQUE(letterboxd_slug)` of the old row, and claiming an `imdb_id` owned by
  another row collided with `UNIQUE(imdb_id)` (the index INC-3 introduced).
- **Fix:** two layers. `2be042c`: TMDB-id remaps now go through the normal anti-flap counter
  (real slug renames with the same tmdb_id were already absorbed by `resolve_films`); also
  implements the ad-hoc backstop — one pre-transaction fetch of `/{user}/films/` page 1 on
  unexplained disappearances (`services/scrape/anti_flap.py`). `a6b8dca`: the old row *yields*
  its slug (tombstoned as `{slug}--superseded-{tmdb_id}`, `services/scrape/film_resolver.py:47`)
  or its imdb_id before the page's current truth is persisted.
- **Commits:** `2be042c`, `a6b8dca` — v1.5.1.
- **Lesson:** external identity mappings are mutable; every UNIQUE constraint on an
  externally-sourced column needs an explicit conflict-resolution protocol, or the first
  remap turns into a permanent crash loop.
- **Tripwire:** any new code writing `films.letterboxd_slug` or `films.imdb_id` outside
  `film_resolver.py`. Review question: "what happens when Letterboxd points this slug at a
  different TMDB id tomorrow?" Check: `grep -n superseded src/watchlistarr/services/scrape/film_resolver.py`.

### INC-2 — "database is locked" — HTTP inside a write transaction

- **Symptom:** any write endpoint (list toggle) returned 500 "database is locked" after 10 s
  whenever the initial run was resolving films — which took ~25 minutes for a 642-film watchlist.
- **Root cause:** SQLAlchemy `flush()` takes the SQLite write lock and holds it until the final
  commit; the scrapers held that transaction open *across HTTP fetches* (2 s rate limit per
  slug). WAL allows exactly one writer; `busy_timeout=10s` fired for everyone else.
- **Fix:** band-aid `321b8d1` (pre-v1.0.0): WAL + `busy_timeout=10000` + `synchronous=NORMAL`
  PRAGMAs in `db.py`, commit every 10 slugs, global exception handler. Real fix `b7a44d2`:
  fetch-first/write-last refactor across all five scrapers; `resolve_film` became batch
  `resolve_films` returning flat `ResolvedFilm` dataclasses safe across sessions;
  `with_scrape_audit` wraps coroutines instead of injecting sessions; regression test runs two
  scrapers under `asyncio.gather`.
- **Commits:** `321b8d1` (in v1.0.0), `b7a44d2` — v1.0.2.
- **Lesson:** never perform HTTP inside a SQLite write transaction; keep write sessions short
  and open them last. This is now a standing code invariant (`watchlistarr-architecture-contract`).
- **Tripwire:** an `await client.…` / network call between a `session.add()`/`flush()` and its
  `commit()` in any `services/scrape/*.py`. Review question: "is all I/O done before the session
  opens?"

### INC-3 — Radarr "No results returned" — the imdb_id blind spot

- **Symptom:** Radarr's list test showed "No results were returned from your import list" on
  every watchlistarr endpoint, despite valid JSON with tmdb_id.
- **Root cause:** Radarr's `StevenLuParser.cs` reads only `title` and `imdb_id`; items without
  `imdb_id` are discarded. The API served only `tmdb_id`.
- **Fix:** `films.imdb_id` column (migration `0004`, partial unique index — the UNIQUE later
  implicated in INC-1), IMDb-link regex in `services/letterboxd/film_page.py`, lazy re-resolve
  when `imdb_id IS NULL`, bulk `scripts/backfill_imdb.py`, serializers include imdb_id.
- **Commits:** `59ad738` — v1.0.1.
- **Lesson:** the consumer's parser, not your schema, defines the contract. Read the consumer's
  source before shipping an integration. Full parser behavior: `radarr-integration-reference`.
- **Tripwire:** any edit to `schemas/radarr.py` / `services/radarr.py` that does not update
  `scripts/smoke.py` in the same commit ("the Radarr payload is sacred" — enforcement gate in
  `watchlistarr-change-control`).

### INC-4 — Scheduler blind spots — unaudited jobs and blocking shutdown

- **Symptom:** the dashboard showed no periodic activity; a persistently failing sync read as a
  stale success; after a crash, lists showed perpetual spinners and toggling never relaunched
  the sync. Earlier: app shutdown hung.
- **Root cause:** periodic scheduler jobs did not run under `with_scrape_audit` — no
  `scrape_runs` rows, no `last_sync_status=error`; RUNNING rows orphaned by a crash were never
  cleaned. Separately, `JobScheduler.shutdown(wait=True)` is synchronous and blocked the event
  loop inside the FastAPI lifespan.
- **Fix:** `9626e15`: all runners wrapped in `with_scrape_audit`; on startup, orphaned RUNNING
  runs marked error; daily prune of `scrape_runs` older than 30 days (RSS every 15 min grew the
  table unboundedly). `00ad6f0`: shutdown delegated via `asyncio.to_thread`.
- **Commits:** `00ad6f0` — v1.2.3; `9626e15` — v1.5.1.
- **Lesson:** background work that is not audited does not exist operationally; failure states
  must be written somewhere an operator looks, and crash-orphaned state must be reconciled at boot.
- **Tripwire:** adding a scheduler job whose runner is not wrapped by `with_scrape_audit`
  (`grep -n with_scrape_audit src/watchlistarr/scheduler.py`), or any long sync call in the
  lifespan/shutdown path.

### INC-5 — Custom-list ordering rot (5-bug cluster)

- **Symptom:** the order Radarr received shuffled over time, sorts did nothing, lowering
  `max_items` changed nothing, and editing a list silently wiped its filters.
- **Root cause / fix, per bug:**
  - Sorts silently ignored: `_choose_from_pool` implemented only `RATING_DESC`;
    LETTERBOXD/REVERSE/RANDOM fell through to `random.sample`. Fixed with a four-branch
    dispatch. `844c5bf` — v1.2.0.
  - `max_items` reduction never truncated: `recalculate()` only filled. Fixed to truncate
    keeping top-N per `sort_order`, plus defense-in-depth `LIMIT` at serve time. `4a28431` — v1.2.2.
  - Duplicate positions after rotate/recalculate (position is not UNIQUE, so no DB error —
    silent shuffling only). Fixed with `_reindex_positions()` reassigning [0..N-1]. `72b2f10` — v1.2.3.
  - Incremental scrapes (page 1 + last page) reassigned positions of existing items from the
    slice index, corrupting order until the next full sync. Fixed with
    `_upsert_items(reassign_positions=False)`; new inserts go to `max(existing)+1`. `25aa6e5` — v1.2.3.
  - `recalculate()` with `max_items=NULL` only removed, never added newly-qualifying films; PUT
    silently cleared any field absent from the payload; invalid enums returned 500. Fixed with
    fill-from-pool, merge semantics (absent = keep, explicit null = clear), 400s. `6e84292` — v1.5.1.
- **Lesson:** derived ordered state (positions) rots silently unless every mutation path
  re-establishes the invariant; partial updates need explicit merge semantics.
- **Tripwire:** any code writing `CustomListItem.position` or `ListItem.position` — ask "who
  reindexes after this?" (`grep -n position src/watchlistarr/services/custom_lists.py`); any
  new PUT handler — ask "what happens to fields the client omits?"

### INC-6 — The cooldown revert (33 minutes)

- **Symptom (motivating):** Radarr's imported set churned — a "top-N by rating" custom list
  reshuffled between polls.
- **Wrong mechanism shipped:** a hard per-list scrape cooldown. Reverted 33 minutes later: the
  churn came from *serve-time* behavior (`serialize_custom_list` re-sorted by current rating on
  every request; `rotate` cycled items), both orthogonal to scrape frequency.
- **Fix (real):** opt-in periodic snapshot mode; serve by persisted position when snapshotting.
- **Commits:** `23fec33` (2026-05-23 18:46) added, `c8991da` (2026-05-23 19:19) reverted — both
  inside v1.4.0; the cooldown never existed in any released version.
- **Lesson:** the proposed mechanism must explain *all* observations before you ship the fix.
- **Tripwire:** any proposal to throttle scrape frequency to stabilize Radarr output. Full
  story with migration fallout in "Reverted / reworked ideas" below; this incident is also the
  worked cautionary example in `watchlistarr-research-methodology`.

### INC-7 — The latent Postgres enum bug SQLite hid

- **Symptom:** none, locally — that is the incident. On Postgres, any `sort_order='rating_desc'`
  write failed with "invalid input value for enum sort_order_enum"; the v1.2.0 RATING_DESC
  feature was broken for Postgres deployments from birth.
- **Root cause:** migration `0003` created `sort_order_enum` without `rating_desc`; SQLite
  serializes enums as unchecked VARCHAR, so tests and dev never noticed.
- **Fix:** migration `0006` — `ALTER TYPE ... ADD VALUE IF NOT EXISTS 'rating_desc'`,
  Postgres-only, no-op on SQLite, no-op downgrade.
- **Commits:** `d8ae10c` — v1.2.3 (bug introduced by `58c94ab`/0003; feature affected since v1.2.0).
- **Lesson:** SQLite masks enum/DDL strictness bugs; every new enum *value* needs a migration
  and Postgres-dialect thinking even if everything real runs on SQLite.
- **Tripwire:** adding a member to any `models/` enum without a paired Alembic migration.
  Check: `grep -rn "Enum(" src/watchlistarr/models/` vs `ls alembic/versions/`.

### INC-8 — The uv.lock release pitfall (bitten twice)

- **Symptom:** `uv sync --frozen` (the first CI step) fails on the release commit/tag because
  `uv.lock` still carries the previous package version.
- **Root cause:** the release bump edits `pyproject.toml` + `__init__.py` but `uv.lock` embeds
  the package's own version; forgetting `uv lock` desynchronizes them.
- **Fix:** first bite at v1.1.0 — follow-up commit `1f03341` ("sync uv.lock con v1.1.0") on
  main. Second bite at v1.2.2 — required `git commit --amend` + delete remote tag + retag +
  force-push of main (the amended `0bb2065` you see today already includes uv.lock; the
  evidence is `0eaed98`'s message and the pitfall note at `.claude/versioning.md:64`). Procedure
  step 5 (`uv lock`, 4-file release commit) added in `0eaed98`.
- **Commits:** `1f03341` (v1.1.0), `0bb2065` amended (v1.2.2), `0eaed98` (procedure).
- **Lesson:** a documented procedure beats memory; a release commit has exactly 4 files
  (`CHANGELOG.md`, `pyproject.toml`, `src/watchlistarr/__init__.py`, `uv.lock`).
- **Tripwire:** `git show <release-sha> --stat` listing 3 files. Release flow is owned by
  `watchlistarr-change-control` / `.claude/versioning.md`.

### INC-9 — Add-user hung the browser; logs vanished after Alembic

- **Symptom:** pressing "add user" froze the browser for minutes; after migrations, no INFO
  logs appeared at all.
- **Root cause:** `run_initial_for_user` (discovery + full watchlist + films backstop, with a
  2 s Letterboxd rate limit per film-page fetch) ran synchronously inside the POST handler. Separately,
  `alembic.fileConfig` reassigned root-logger handlers, silencing post-migration logging.
- **Fix:** `293d4d5`: background `asyncio.create_task` with a GC-safe module-level reference
  set, immediate redirect, `setup_logging` re-run after Alembic (`force=True`). `3bb9ea8`:
  per-step audit + commit and per-page/per-film logs so partial progress is visible and survives
  a partial failure.
- **Commits:** `293d4d5`, `3bb9ea8` — 2026-05-20, pre-v1.0.0.
- **Lesson:** never run unbounded scraping inside a request handler; background tasks need
  retained references and per-step persistence/visibility.
- **Tripwire:** a route handler that directly awaits any `services/scrape/*` or onboarding
  coroutine instead of scheduling it.

### INC-10 — Naive/aware datetime TypeError every rotation tick

- **Symptom:** `TypeError: can't compare offset-naive and offset-aware datetimes` hourly in
  `rotation_tick`.
- **Root cause:** SQLite drops tzinfo on `DateTime` columns declared without `timezone=True`;
  `last_rotated_at` re-read naive and was compared against aware `utcnow()`.
- **Fix:** normalize to UTC-aware in `rotate()` (`replace(tzinfo=UTC)` when naive); regression
  test forces a DB round-trip in a fresh session.
- **Commits:** `86680a1` — v1.2.1.
- **Lesson:** any datetime read back from SQLite may be naive; normalize at the read/compare
  boundary, and a regression test must round-trip through the DB to catch it.
- **Tripwire:** arithmetic between a DB-loaded datetime and `datetime.now(UTC)`/aware values
  without a naive-check. Check: `grep -rn "timezone=True" src/watchlistarr/models/` (mostly absent).

### INC-11 — Disabled lists still served to Radarr

- **Symptom:** Radarr kept importing items from lists the user had disabled in the UI.
- **Root cause:** `/{username}/{slug}/` and `/{username}/watchlist/` never checked
  `List.enabled`, although `.claude/radarr-custom-list.md` required it.
- **Fix:** 404 when disabled (`routes/api/radarr.py:75,100`); smoke.py asserts added in the
  same commit.
- **Commits:** `646ca47` — v1.5.1.
- **Lesson:** a documented contract clause without a test is a wish. Note the sibling gap that
  was NOT fixed: `custom_lists.enabled` is still never checked (see Latent risks).
- **Tripwire:** adding a Radarr-facing route without an `enabled` check and a matching
  smoke/integration assert.

### INC-12 — `lists` was never reserved as a username

- **Symptom:** a user named `lists` could be registered but could never be served — the root
  route `/lists/{slug}/` shadows it.
- **Root cause:** routing assumed the reservation; `validate_username` never enforced it.
- **Fix:** single reserved-names constant in `services/scrape/initial_run.py`, imported by the
  Radarr routes. Same commit: RSS logs skipped non-movie items; User-Agent derives from
  `__version__` (was pinned at 1.0.0); dead helper removed.
- **Commits:** `5a9bc52` — v1.5.1.
- **Lesson:** every root-level path segment is a stolen username; reservations must live in one
  imported constant, not in comments.
- **Tripwire:** adding any new root-level route without extending the reserved-names constant
  (`grep -rn RESERVED src/watchlistarr/`).

### INC-13 — CI broke on a floating action tag

- **Symptom:** CI failed immediately after a routine actions upgrade for the Node.js-24 runner
  deadline.
- **Root cause:** `daf3e35` referenced `setup-uv@v8`; that floating tag does not exist upstream
  (only exact tags like `v8.2.0`).
- **Fix:** pin to `v8.2.0` (`a394ad6`); process rule added — ci.yml changes are validated on a
  remote dev run (every action ref checked to exist) before merging to main (`4439c17`,
  `.claude/rules.md`).
- **Commits:** `daf3e35`, `a394ad6` — v1.5.2; `4439c17` (rule, HEAD).
- **Lesson:** action refs are external identifiers with no local verification; validate remotely
  before merge.
- **Tripwire:** any edit to `.github/workflows/ci.yml` `uses:` lines merged without a green
  remote run on dev. Check: `grep -n "uses:" .github/workflows/ci.yml`.

## Reverted / reworked ideas — fenced-off wrong paths

Do NOT re-propose any of these without new evidence that the original rejection reason no
longer holds. Cite the fence when declining.

### The scrape cooldown (0007 → 0008, 33 minutes) — full story

`23fec33` (2026-05-23 18:46) shipped a hard per-list sync cooldown: `lists.min_sync_interval`
and `users.watchlist_min_sync_interval` (migration `0007_min_sync_interval`), guards in the
scheduler's `_run_*` wrappers emitting `scheduler.cooldown_skip`, a "Min interval between
syncs" UI field with 24h/168h/720h hints, and 78 lines of interval tests. The guard was placed
in the wrappers — not in `sync_*` — so a future "force sync" button could bypass it. That
**UI button** was never built; its raison d'être left with the revert. Today's force-sync
mechanisms are toggle off→on (immediate scrape on add/enable, via `41a1ed3`,
`routes/api/v1.py:578-591`) and `POST /admin/refresh/{job_id}` — see
`watchlistarr-run-and-operate`.

`c8991da` (2026-05-23 19:19 — 33 minutes later) removed all of it. The diagnosis was wrong:
Radarr's output churned because `serialize_custom_list` re-sorted by *current* rating on every
request and `rotate` cycled items on its own interval — both fully orthogonal to how often
Letterboxd was scraped. No cooldown on scrapes could stop either. Replacement: opt-in
**periodic snapshot** mode per custom list — `custom_lists.snapshot_interval` /
`last_snapshot_at`, `refresh_snapshot()` regenerates the set from scratch on the rotation tick,
and serve-time re-sorting is disabled in snapshot mode (serve by persisted `position`).
Migration `0008_swap_cooldown_for_snapshot` drops the 0007 columns; 0007 stays in the chain
forward-only, so every fresh DB creates then drops two columns. Both commits shipped inside
v1.4.0; the cooldown never existed in any released version.

**Fences:** (1) do not re-propose scrape-frequency throttling to stabilize Radarr output —
serve-time behavior is the churn mechanism; (2) do not "clean up" the dead 0007/0008 pair on a
live DB. This story is also the worked example in `watchlistarr-research-methodology`
(mechanism must explain all observations before you ship); that is its only other full home.

### Global settings table → per-entity overrides

`a967bbd` (2026-05-20, pre-v1.0.0, migration `0002_settings_per_entity`) dropped the `settings`
table, the `Setting` model, `services/settings.py`, and the `/settings` screen. Replaced by:
env vars as immutable-after-boot defaults + nullable override columns on `users`/`lists`,
resolved in `services/intervals.py`. **Settings precedence**: interval overrides resolve via
`or` — `effective = entity_override or env_default` — so a falsy override (NULL **or 0**)
falls through to the env default; ONLY `flap_confirm_scrapes` resolves via `is None`, so a
stored 0 is honored there (the API coerces 0→None; anti-flap treats threshold 0 like 1).
(`services/intervals.py:10-41`) **Fence:** do not reintroduce a global runtime-settings table.
tech-stack.md still describes the old table — wrong as of 2026-07, see the standing errata
table in `watchlistarr-docs-and-writing`. Precedence details: `watchlistarr-config-and-flags`.

### HTMX + Pico → React SPA (~12 hours after the MVP, same day)

Docs (`28b09a5`, May 19) chose HTMX/Pico; the MVP (`554a808`) shipped it. `58c94ab` (May 20
17:09) redid the UI as 5 English tabs; `434e250` + `72ff656` (May 20 evening) rebuilt it as a
React 18 dark-theme SPA with **no build step** (`@babel/standalone` vendored in
`static/vendor/`), deleting `routes/ui/` and templates and creating `/api/v1` (`routes/api/v1.py`).
The Activity feed changed from a `scrape_runs` DB feed to an in-memory stdout ring buffer.
**Fence:** do not propose returning to server-rendered HTMX, and do not add a JS build
step/bundler — no-build babel-standalone is a deliberate constraint (`.claude/tech-stack.md`).

### Sublists + predefined combos → multi-source custom lists (intentional breaking change)

The May-19 docs speak of "listas combinadas"/"sublistas"; the MVP implemented `Sublist` plus
three *predefined* combined endpoints (`/all/watchlist/<combo>/`, `/all/<slug>/`). `58c94ab`
(migration `0003_custom_lists_multisource`) renamed `Sublist` → `CustomList`, added
`custom_list_sources` + `custom_list_excluded_watchers` and enums `CombinationOp`/`SourceRole`,
deleted `CombinedKind`, `combined.py`, `rotation.py` and the predefined endpoints — commit
message: "Rotura intencional: hay que reconfigurar Radarr". It also made the watchlist a normal
discovered list. v1.5.0 (`7527121`, migration `0009`) extended sources polymorphically (custom
lists as sources/subtracts of other custom lists, BFS cycle check). **Fence:** do not
reintroduce predefined global combo endpoints; composition happens through custom-list sources.

### MIT → GPL-3.0-or-later (same day)

`bb3a303` (Jun 11, go-public prep, shipped in v1.5.1) added an MIT LICENSE; `6507458` switched
to GPL-3.0-or-later hours later (v1.5.2). Same prep commit also switched CHANGELOG.md from
Spanish to English (public-facing; internal `.claude/` docs stay Spanish). **Fence:** the
license is GPL-3.0-or-later — do not "fix" LICENSE back to MIT; new dependencies must be
GPL-compatible.

## Latent risks never fixed (honest list — candidate/open, not scheduled work)

Live-problem work is planned in `watchlistarr-hardening-campaign`; doc-drift entries are in the
errata table in `watchlistarr-docs-and-writing`. As of 2026-07, v1.5.2:

- **`custom_lists.enabled` is a dead flag** (candidate): default True (`models/custom_lists.py:56`),
  exposed read-only in JSON (`routes/api/v1.py:299`), no endpoint toggles it, and
  `/lists/{slug}/` never checks it (`routes/api/radarr.py:39-51`) — the exact gap INC-11 fixed
  for raw lists.
- **Per-client rate limiting, parallel jobs** (open — campaign track a): the Letterboxd
  throttle lock is per-`LetterboxdClient` instance and the scheduler builds a fresh client per
  job (`scheduler.py:260,279,310`), so concurrent jobs hit Letterboxd in parallel.
- **`users.rss_interval` / `films_backstop_interval` / `discovery_interval` unsettable**
  (candidate): honored by the scheduler but no endpoint or UI writes them — DB-edit only
  (`grep -n rss_interval src/watchlistarr/routes/api/v1.py` → no hits).
- **`added_after`/`added_before` unreachable** (candidate): honored by `_apply_filters`
  (`services/custom_lists.py:179-215`) but no endpoint parses them.
- **`Settings.http_port` is dead code** (candidate): defined at `config.py:42`, referenced
  nowhere; the container hardcodes 8080 (Dockerfile EXPOSE/CMD); `HTTP_PORT` only moves the
  host-side compose mapping.

## CHANGELOG discrepancy (do not propagate)

`CHANGELOG.md:113` (v1.4.0 "Removed") claims the scrape cooldown was "introduced in v1.3.0".
Git contradicts this: `23fec33` (2026-05-23 18:46) postdates the v1.3.0 release commit
`991ddbc` (2026-05-22) by ~23 h; add (`23fec33`) and remove (`c8991da`) both shipped inside
v1.4.0. When citing the cooldown story, cite the commits, not the CHANGELOG sentence.

## Provenance and maintenance

All SHAs verified resolvable and matching their described diffs on 2026-07-02 at HEAD `4439c17`.
Re-verify before trusting any entry after history-affecting operations:

- Any cited commit: `git show <sha> --stat` (subject + touched files must match the story).
- Tags/versions: `git ls-remote --tags origin` (13 tags v1.0.0–v1.5.2; none fetched locally).
- Timeline dates: `git log --format='%h %ad %s' --date=short --reverse | head -20`.
- Commit counts: `git rev-list --count 4439c17` and `git rev-list --count --no-merges 4439c17`
  (counting `HEAD` includes post-anchor docs/skills commits).
- Cooldown 33-minute window: `git show -s --format='%h %ad %s' 23fec33 c8991da`.
- Dead migration pair: `ls alembic/versions/` (0007 and 0008 both present).
- CHANGELOG discrepancy: `grep -n "introduced in v1.3.0" CHANGELOG.md`.
- Tombstone protocol: `grep -n superseded src/watchlistarr/services/scrape/film_resolver.py`.
- Disabled-list checks: `grep -n "enabled" src/watchlistarr/routes/api/radarr.py` (raw-list
  routes check; custom-list route does not).
- uv.lock pitfall note: `grep -n "Pitfall" .claude/versioning.md`.
- Dead http_port: `grep -rn http_port src/watchlistarr/`.
- Unsettable columns: `grep -n "rss_interval\|added_after" src/watchlistarr/routes/api/v1.py`
  (expect no hits) vs `grep -n "added_after" src/watchlistarr/services/custom_lists.py`.

If a future commit fixes a latent risk above, move it from this list into a new incident entry
(or delete it) in the same PR — this file is the single home of incident history.
