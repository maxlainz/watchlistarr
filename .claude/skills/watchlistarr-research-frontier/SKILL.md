---
name: watchlistarr-research-frontier
description: Ranked frontier bets for watchlistarr — where to invest next to make it the most reliable *arr list source ("boring excellence" = provable zero-flap, provable gentleness, restart-safe, crash-only) and to practice scraping resilience as a discipline (selector-drift early warning, loud degradation via a failure taxonomy, fixture contract tests). Also owns THE CLAIMS-EVIDENCE RULE (no public capability claim without a named in-repo test or command), the external positioning section (name collision, honest differentiators), and the project NON-GOALS - check here BEFORE designing any new source or consumer integration (Trakt, Plex, IMDb, Sonarr, other *arr apps) or any recommendation/curation feature; these are owner-rejected directions. Use when choosing the next ambitious investment, when asked to add a new source/integration, when writing or reviewing README / release-note / docs feature claims, or when positioning the project against other list tools. NOT for executing hardening work now → `watchlistarr-hardening-campaign`; NOT for evidence-bar methodology or predict-before-run worksheets → `watchlistarr-research-methodology`.
---

# watchlistarr — research frontier

Ranked bets under the owner's definition of ambition (decision 2026-07): **boring excellence**
(be the most *reliable* \*arr list source — provable, not asserted) plus **scraping resilience as
a discipline** (drift detection, loud degradation, fixture contract tests). Each bet names the
in-repo asset that makes it cheap here, the first three steps, and a falsifiable finish line.

Definitions used below (define once, use everywhere):

- **Flap**: an item disappearing from a served Radarr list and reappearing later, causing Radarr
  to remove/re-add movies. **Hysteresis**: requiring repeated confirmations before removal.
- **Gentleness**: a measurable ceiling on outbound requests to Letterboxd.
- **Drift**: Letterboxd changing HTML structure so parsers silently return less/nothing.
- **Crash-only**: the process can be killed at any instant (`kill -9`) and the next boot converges
  with no corruption and no manual repair.
- **Materialized custom list**: `custom_list_items` rows are the served truth, written ahead of
  time — not recomputed per request (`src/watchlistarr/services/custom_lists.py:94-116`).

## When to use

- "What should we build next?" / "what makes this project ambitious?" — pick a bet below.
- You are about to add a feature bullet to `README.md`, `CHANGELOG.md`, or a release note →
  apply the claims-evidence rule first.
- You want to compare watchlistarr against other \*arr list tools, or write public positioning.
- A frontier bet graduated into implementation and you need its "you have a result when…" gate.

## When NOT to use

- Executing the four live hardening problems (anti-bot, zero-flap engineering, first-sync
  latency, custom-list correctness debt) → `watchlistarr-hardening-campaign` owns the phased
  campaign; this skill only defines the proof artifacts some tracks feed.
- How to run an experiment / evidence bar / idea lifecycle → `watchlistarr-research-methodology`.
- What the anti-flap formula or Radarr contract *is* → `watchlistarr-architecture-contract`,
  `radarr-integration-reference`.
- Fixing doc errors → `watchlistarr-docs-and-writing` (standing errata table lives there).

## Non-goals (explicit, user decision 2026-07)

| Rejected direction | Why not |
|---|---|
| Curation intelligence (recommendations, taste profiles, "smart" pick algorithms) | Out of scope by owner decision: watchlistarr moves lists faithfully; it does not decide what you should watch. |
| Ecosystem breadth (Sonarr/TV, Trakt/IMDb/Plex sources, more \*arr targets) | Out of scope by owner decision: depth on one source (Letterboxd) and one consumer (Radarr) beats a shallow matrix; breadth items may only ever appear as explicitly-labeled candidates. |

## THE CLAIMS-EVIDENCE RULE (law)

> **No public capability claim (README, docs, release notes) without a named in-repo test or
> command that demonstrates it. A claim→evidence table is mandatory for README feature bullets.**

Enforcement: before merging any change to `README.md` feature bullets or `CHANGELOG.md`
capability lines, update the table below (or its successor) in the same commit. If no evidence
exists, either write the test first or downgrade the wording. Public claims ship through the
normal `watchlistarr-change-control` flow — never push them to `main` directly. Positioning
claims (see the last section) obey this same rule.

### Worked example: README feature bullets → evidence (as of 2026-07, v1.5.2, `README.md:16-21`)

| README bullet | Evidence (named test / smoke assert / code path) | Verdict |
|---|---|---|
| "Multi-user — follow as many Letterboxd accounts as you want" | `scripts/smoke.py:287` (seeds+asserts alice & bob), `scripts/smoke.py:315-332` (serves alice's watchlist); `tests/integration/test_radarr_routing.py` | Solid |
| "Smart custom lists — merge several lists into one" | `tests/integration/test_radarr_routing.py:227-249` (union / intersection / exclude-watched); `scripts/smoke.py:328-364` (union, source-of-source) | Solid |
| …"exclude movies somebody has already watched" | `tests/integration/test_radarr_routing.py:243`; `scripts/smoke.py:343-352` (alice's watched film excluded from top-rated) | Solid |
| …"filter by rating or release year" | Year: `scripts/smoke.py:334-341` (`year_last_n`), `tests/integration/test_rotation.py:299-359`. Rating: code path only (`src/watchlistarr/services/custom_lists.py:189-192`) — `grep -rn "min_rating" tests/ scripts/` returns nothing | **THIN — rating filter has zero test coverage; write a test or soften the bullet** |
| "Steady rotation — 5 movies a week … at your pace" | `tests/integration/test_rotation.py:243` (interval respected), `:432` (swaps oldest), `:471` (positions stay unique/consecutive); model fields `src/watchlistarr/models/custom_lists.py:50-52` | Solid at integration level; no end-to-end smoke assert (acceptable) |
| "Safe removals — must disappear several times in a row before it's dropped" | `tests/integration/test_scrape_anti_flap.py` (5 tests: watched-immediate, remap-through-counter, films-page backstop, counter increment, threshold removal) | Solid example-level; **B1 upgrades this to a property-level guarantee** |
| "Everything in the browser … Changes apply instantly, no restarts" | Toggle→immediate sync `src/watchlistarr/routes/api/v1.py:578-591`; SPA shell + bootstrap asserts `scripts/smoke.py:266-312`; `tests/integration/test_ui_smoke.py` | Partial — server side evidenced; no browser-driven test exercises the SPA itself |
| "One small container — amd64 and arm64" | Multi-arch build `.github/workflows/ci.yml:96` (`platforms: linux/amd64,linux/arm64`) | Build evidenced; "small" is unquantified — no image-size check exists |

History: `README.md:112` once promised a per-list ⚙ refresh button that never existed (fixed
2026-07-02; E30 in `watchlistarr-docs-and-writing`'s resolved list) — the canonical example of
the failure mode this rule exists to prevent: a claim nobody could demonstrate. (The button still
does not exist; the real mechanisms are toggle off→on, `routes/api/v1.py:578-591`, or
`POST /admin/refresh/{job_id}`, `routes/api/admin.py:8`.)

## Ranked frontier bets

Ranking basis: B1–B2 are the product promise and the existential risk, in that order; B3–B4 are
the resilience discipline; B5–B6 round out "boring excellence". "SOTA" below means other \*arr
list tools/bridges generally; capability-gap statements about them are phrased generically and
labeled `(unverified externally)` — verify before repeating any of them publicly.

### B1 — Provable zero-flap: the guarantee, not just the mechanism

**Why current SOTA falls short.** List tools typically re-serve whatever the last fetch
returned, so any scrape hiccup propagates straight into Radarr as a removal; none we know of
implement removal hysteresis, let alone state it as a tested guarantee `(unverified externally)`.
The frontier is a *published, machine-checked* guarantee: **"no removal without K confirmations
or watched-evidence."**

**This repo's asset.** The counter machinery already exists and is the exact invariant:
`reconcile_full_scrape` (`src/watchlistarr/services/scrape/anti_flap.py:88-154`) increments
`pending_removal_count` (`:146-147`) and deletes only at threshold, with watched-evidence
shortcuts (`:120-144`); reappearance resets the counter in the orchestrator
(`src/watchlistarr/services/scrape/watchlist.py:76`); incremental scrapes never remove; the whole
reconcile runs inside one write transaction committed atomically with the upsert
(`src/watchlistarr/services/scrape/lists.py:81-97`). Canonical formula (home:
`watchlistarr-architecture-contract`; stated verbatim because this bet formalizes it):

> **Anti-flap removal rule** (applies ONLY to full scrapes; incremental scrapes never remove):
> when a full scrape finds an item in `list_items` but not in the scrape result —
> (1) if owner has `(user_id, tmdb_id)` in `watched_films` → remove immediately;
> (2) else ad-hoc fetch `/{user}/films/` page 1 (before the write transaction): if present →
> insert `watched_films` with `source='films-page'` and remove immediately;
> (3) else `pending_removal_count += 1`; remove only when `pending_removal_count >=` effective
> flap threshold (list's `flap_confirm_scrapes` override, else env `FLAP_CONFIRM_SCRAPES`,
> default 3); (4) reappearance in ANY scrape resets `pending_removal_count = 0`.
> (`services/scrape/anti_flap.py`)

**First three steps in this repo.**
1. Add `hypothesis` to the dev dependency group in `pyproject.toml` (next to pytest,
   `pyproject.toml:30-33`) and refresh `uv.lock` in the same commit (see
   `watchlistarr-build-and-env` for lockfile discipline).
2. Write `tests/integration/test_anti_flap_properties.py`: generate arbitrary sequences of
   full-scrape results (sets of tmdb_ids) interleaved with watched-events and films-page hits;
   drive `_upsert_items` + `reconcile_full_scrape` per step; assert the invariant — an item is
   deleted only if watched-evidence existed at deletion time OR it was absent from ≥ threshold
   consecutive full scrapes with no intervening reappearance.
3. Prove the test has teeth (mutation check): temporarily flip `>=` to `>` at
   `anti_flap.py:147`, and separately delete the reset at `watchlist.py:76` — the property test
   must fail for both; revert. Only then draft the public guarantee sentence for `README.md`,
   routed through `watchlistarr-change-control` with this test named as evidence.

**You have a result when** `uv run pytest tests/integration/test_anti_flap_properties.py`
passes on hundreds of generated sequences AND fails under both mutations of step 3.

### B2 — Provable gentleness: a measured global request ceiling

**Why current SOTA falls short.** Scraping-backed tools rarely publish measured request rates;
"we rate limit" is asserted, not demonstrated, and per-component limiters that multiply under
concurrency are a common silent failure `(unverified externally)`. The frontier artifact is a
number: "watchlistarr never exceeds N requests to Letterboxd per minute, and here is the test."

**This repo's asset — and the known hole.** `LetterboxdClient` enforces 2s spacing per
*instance* via a lock (`src/watchlistarr/services/letterboxd/client.py:15,46-47,63-71,77-83`,
tested at `tests/unit/letterboxd/test_client.py:76`), but each scheduler job constructs its own
client (`src/watchlistarr/scheduler.py:260,279,310`; onboarding too,
`src/watchlistarr/services/onboarding.py:99,167`; plus ad-hoc clients at
`src/watchlistarr/routes/api/v1.py:509` on user creation and in `scripts/backfill_imdb.py:28` /
`scripts/backfill_ratings.py:29` — 6 sites in `src/` + 2 in `scripts/`), so M concurrent jobs
run at M× the intended rate. `watchlistarr-hardening-campaign` Track A owns *implementing* the shared budget; this bet
owns the **proof artifact**: request-log audit plus published numbers.

**First three steps in this repo.**
1. Instrument the choke point: emit a structured `letterboxd.request` log line (URL path +
   monotonic timestamp) inside `LetterboxdClient.get` (`client.py:63-71`) so every outbound
   request is auditable from the Activity buffer and test captures.
2. Write `tests/integration/test_global_request_rate.py` (respx transports, no live traffic):
   run several list/watchlist syncs concurrently the way the scheduler does, capture all request
   timestamps, and compute the max requests in any sliding 10s window. Mark it `xfail(strict=True)`
   with the ceiling assertion — today it MUST fail, which quantifies the gap for Track A.
3. When Track A lands the shared budget, remove the xfail; record the measured ceiling in the
   claims-evidence table and only then publish it (README/docs) via `watchlistarr-change-control`.

**You have a result when** `uv run pytest tests/integration/test_global_request_rate.py` passes
un-xfailed, asserting a named ceiling (e.g. ≤ 1 request / 2s globally) under concurrent jobs —
and the published README number cites that test.

### B3 — Selector-drift early warning: contract tests vs live HTML

**Why current SOTA falls short.** Scrapers typically learn about upstream HTML changes when
production breaks — parsers returning empty lists look like "the list emptied", which is the
worst possible failure for a Radarr feed. Scheduled structure-diffing against live pages is rare
`(unverified externally)`.

**This repo's asset.** Parsers are pure functions isolated in
`src/watchlistarr/services/letterboxd/` (`lists.py`, `films.py`, `film_page.py`, `rss.py`) and
already run against a frozen fixtures corpus — `ls tests/fixtures/` (8 files as of 2026-07:
list/watchlist/films pages, film pages, pagination blocks, RSS) loaded via
`tests/unit/letterboxd/conftest.py`. The same assertions can run against live HTML, diffing
*structure* (non-empty, fields present, pagination parsed) not content.

**First three steps in this repo.**
1. Extract the structural expectations shared by the fixture tests into small assert helpers
   (e.g. in `tests/unit/letterboxd/`), so fixture tests and the live check consume one source of
   truth instead of drifting apart.
2. Write `scripts/drift_check.py`: fetch a small fixed set of public pages through
   `LetterboxdClient` (inherits UA, 2s spacing, retries; refuses to run when
   `LETTERBOXD_OFFLINE=true`, `client.py:64-65`), run every parser, exit non-zero with a
   per-parser report naming what broke. Note: CI does not lint `scripts/` — lint locally with
   the house command (see `watchlistarr-validation-and-qa`).
3. Schedule it OUTSIDE default CI (manual `workflow_dispatch` or an owner-side cron) — never in
   the per-push pipeline: CI must stay deterministic and must not hit live Letterboxd. Any edit
   to `.github/workflows/` goes through the ci.yml self-change protocol in
   `watchlistarr-change-control`.

**You have a result when** `uv run python scripts/drift_check.py` exits 0 today, and — verified
by feeding it a deliberately mangled saved page — exits non-zero naming the affected parser,
i.e. a Letterboxd markup change would page you before it rots production syncs.

### B4 — Loud degradation: a typed failure taxonomy in `scrape_runs`

**Why current SOTA falls short.** Sync tools commonly log-and-continue; failures blur into
staleness and users discover problems as Radarr-side symptoms. Distinguishing "upstream is
blocking us" from "our parser broke" from "our DB hiccuped" at a glance is uncommon
`(unverified externally)`.

**This repo's asset.** Every scheduled scrape already funnels through ONE choke point:
`with_scrape_audit` (`src/watchlistarr/services/scrape/audit.py:40-62`) writes a `ScrapeRun` and
stores `str(exc)[:2000]` into `scrape_runs.error`
(`src/watchlistarr/models/scrape_runs.py:39`). The gap: the reason is free text and
`ScrapeStatus` is only SUCCESS/ERROR/RUNNING (`src/watchlistarr/models/enums.py:21-33`) — a
Cloudflare 403, a timeout, an empty-parse, and an IntegrityError all look identical.

**First three steps in this repo.**
1. Define a `FailureKind` enum (candidate values: `http-403`, `http-5xx`, `timeout`,
   `parse-empty`, `db-integrity`, `offline-blocked`, `interrupted`) and an exception→kind
   classifier applied in the single `except` at `audit.py:59-62`; classify the boot-time
   "interrupted by restart" write (`audit.py:32`) too.
2. Add nullable `scrape_runs.error_kind` via a new Alembic migration (follow existing numbering;
   mind the SQLite-masks-enum-strictness lesson — see `watchlistarr-failure-archaeology`,
   migration 0006 incident), and surface it through the Activity/API serializers.
3. Extend `tests/integration/test_audit.py` with one test per kind (respx-simulated 403/5xx/
   timeout; forced IntegrityError; `LETTERBOXD_OFFLINE=true`), asserting the stored `error_kind`.

**You have a result when** `uv run pytest tests/integration/test_audit.py -k error_kind` passes
and a simulated 403 produces a `scrape_runs` row with `error_kind='http-403'` — making "Letterboxd
is blocking us" a queryable fact instead of a log-archaeology exercise.

### B5 — Restart-safe everything: resumable initial runs

**Why current SOTA falls short.** Long first syncs are usually all-or-nothing: restart mid-way
and tools either re-fetch everything or strand partial state until the next periodic pass
`(unverified externally)`. For thousands-film watchlists (tens of minutes, `README.md:68`) this
is the difference between "restart whenever" and "don't touch it".

**This repo's asset.** Onboarding already audits every step individually via `with_scrape_audit`
(`_run_step`, `src/watchlistarr/services/onboarding.py:73-86`; `_initial_run` at `:89-146`),
boot marks orphaned RUNNING runs as errors
(`fail_interrupted_runs`, `src/watchlistarr/services/scrape/audit.py:17-37`, called at
`src/watchlistarr/main.py:58`), each list carries `last_sync_status` (NEVER/SUCCESS/ERROR), and
`sync_list_full` is an idempotent upsert in one transaction (`services/scrape/lists.py:60-105`) —
re-running a finished list is harmless. The gap: `_initial_run` is a fire-and-forget asyncio
task (`schedule_initial_run`, `onboarding.py:147-157`); a restart kills it and nothing resumes
the un-synced remainder.

**First three steps in this repo.**
1. Add a resume query to `onboarding.py`: users owning lists with `last_sync_status == NEVER`
   (the exact state pre-synced-then-interrupted lists are left in).
2. Call it in the lifespan right after `fail_interrupted_runs` (`main.py:58`), re-scheduling
   `schedule_initial_run`-style work for only the unfinished lists; guard against double-runs
   the same way the toggle endpoint does (in-flight RUNNING check,
   `src/watchlistarr/routes/api/v1.py:578-591`).
3. Write `tests/integration/test_onboarding_resume.py`: seed a user with three lists (one
   SUCCESS, two NEVER), simulate boot, assert exactly the two NEVER lists get new audited runs
   and the SUCCESS one does not.

**You have a result when** that test passes, and a manual QC run (kill the container
mid-onboarding, restart) shows the Activity tab syncing only the remaining lists — no re-adding
the user, no duplicate work.

### B6 — Crash-only operation, proven: `kill -9` anywhere, converge on boot

**Why current SOTA falls short.** "Restart the container" is folk-remedy advice precisely
because most tools cannot promise a hard kill is safe; crash-injection proof for a hobbyist-tier
sync tool is essentially unheard of `(unverified externally)`.

**This repo's asset.** The ingredients are in place: WAL + `busy_timeout` + FK pragmas on every
connection (`src/watchlistarr/db.py:21-30`), `alembic upgrade head` at every boot
(`src/watchlistarr/main.py:52`), orphan-run cleanup at boot (`main.py:58`), and fetch-first /
write-last syncs whose DB effects land in one atomic commit (`services/scrape/lists.py:81-97`).
What's missing is the *proof harness* that turns those ingredients into a stated guarantee.

**First three steps in this repo.**
1. Write `tests/integration/test_crash_convergence.py`: run a fixture-backed full sync,
   cancelling the task at randomized await points (cancellation approximates a crash for
   transaction atomicity), then re-run to completion and assert the final DB state equals an
   uninterrupted baseline run.
2. Write `scripts/crash_smoke.py` modeled on `scripts/smoke.py` (subprocess uvicorn, temp DB,
   `LETTERBOXD_OFFLINE=true`): SIGKILL the server at random delays during seeded activity, then
   reboot and assert `/healthz` is 200, `PRAGMA integrity_check` returns `ok`, and no
   `scrape_runs` row is stuck RUNNING.
3. Loop step 2 N times (N≥20) in the script itself; on green, add the crash-only sentence to the
   claims-evidence table and docs via `watchlistarr-change-control`.

**You have a result when** both `uv run pytest tests/integration/test_crash_convergence.py` and
`uv run python scripts/crash_smoke.py` pass, giving you a demonstrated (not asserted)
crash-only claim.

## External positioning

- **Name collision (know this before writing anything public).** A well-known, unrelated
  "Watchlistarr" project exists that syncs *Plex* watchlists to Sonarr/Radarr `(unverified
  externally, from prior knowledge; verify before citing publicly)`. Never assume inbound users
  mean this repo; any public comparison must first disambiguate.
- **Honest differentiators, as evidenced in-repo** (each already mapped in the claims-evidence
  table above): multi-user Letterboxd ingestion (`scripts/smoke.py:287`); anti-flap removal
  hysteresis (`tests/integration/test_scrape_anti_flap.py`); zero API keys — public HTML/RSS
  only, one container, one SQLite file (`README.md:5,106`); materialized custom lists with
  rotation and snapshot mode (`src/watchlistarr/services/custom_lists.py:94-116,451,527`,
  `tests/integration/test_rotation.py:646`).
- **Rule**: positioning claims obey the claims-evidence rule. Comparative claims about other
  tools additionally require external verification at publication time — this environment cannot
  verify them, so drafts written here must carry `(unverified externally)` until checked.

## Provenance and maintenance

Facts here were verified by reading the repo at HEAD `4439c17` (2026-07, v1.5.2). Re-verify
before relying on any of them:

| Fact | Re-verify with (from repo root) |
|---|---|
| Anti-flap counter + threshold + reset | `grep -n "pending_removal_count" src/watchlistarr/services/scrape/anti_flap.py src/watchlistarr/services/scrape/watchlist.py` |
| Per-instance rate limit (2s) | `grep -n "MIN_INTERVAL_SECONDS\|asyncio.Lock" src/watchlistarr/services/letterboxd/client.py` |
| One client per scheduler job (B2 gap; 6 sites in src/ + 2 in scripts/) | `grep -rn "LetterboxdClient(" src/ scripts/` |
| Audit wrapper + boot orphan cleanup | `grep -n "def with_scrape_audit\|def fail_interrupted_runs" src/watchlistarr/services/scrape/audit.py && grep -n "fail_interrupted_runs" src/watchlistarr/main.py` |
| `scrape_runs.error` free text, no kind column | `grep -n "error" src/watchlistarr/models/scrape_runs.py` |
| WAL/busy_timeout pragmas | `grep -n "PRAGMA" src/watchlistarr/db.py` |
| Fixtures corpus inventory | `ls tests/fixtures/` |
| README feature bullets (and L112 still refresh-button-free) | `sed -n '14,22p;110,114p' README.md` |
| Rating filter untested (THIN verdict) | `grep -rn "min_rating" tests/ scripts/` — no output means still untested |
| `hypothesis` not yet a dependency (B1 step 1) | `grep -n "hypothesis" pyproject.toml` — no output means still absent |
| Multi-arch build claim | `grep -n "platforms" .github/workflows/ci.yml` |
| Onboarding fire-and-forget task (B5 gap) | `grep -n "create_task" src/watchlistarr/services/onboarding.py` |

Maintenance triggers: update the claims-evidence table whenever `README.md:14-21` changes; when
a bet's "you have a result when" test lands, mark the bet **graduated** here and hand ongoing
work to `watchlistarr-hardening-campaign` / normal change flow. (The README refresh-button
erratum was fixed 2026-07-02 and its note here was dropped per this trigger, keeping only the
one-line history above.)
