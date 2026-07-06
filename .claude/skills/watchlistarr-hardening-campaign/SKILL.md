---
name: watchlistarr-hardening-campaign
description: Executable, decision-gated campaign playbook for the four ranked live problems of watchlistarr — (A) Letterboxd anti-bot resilience / global rate limiting / Cloudflare 403 recovery, (B) zero-flap guarantee for Radarr (dead custom_lists.enabled flag, selector-drift tripwires, empty-scrape mass-delete risk, chained-list staleness), (C) first-sync latency at scale (thousands-film watchlists taking tens of minutes), (D) custom-list correctness debt (duplicate positions, max_items, PUT merge, snapshot precedence). Use when asked to "harden", "make more robust", "fix rate limiting", "prevent mass deletes", "speed up initial sync", or to pick up campaign work. NOT for diagnosing a live incident right now → use `watchlistarr-debugging-playbook`. NOT for the full history of past failures → use `watchlistarr-failure-archaeology`. NOT for how to commit/merge/release the resulting change → use `watchlistarr-change-control` (every track promotes through it).
---

# watchlistarr hardening campaign

Four ranked tracks over the owner's four hardest live problems (as of 2026-07, v1.5.2, HEAD `4439c17`).
Each track = numbered phases; each phase = exact commands from repo root + expected observable result
+ branch instructions. You do not need prior context: run the phase, compare against "Expect", follow
the arrow. Nothing in this file is implemented yet unless a phase says "already in code".

## When to use

- You were asked to work on scraping resilience, rate limiting, or 403 handling → Track A.
- You were asked to guarantee Radarr never sees a spurious mass-removal ("flap" = an item
  disappearing and reappearing from the served JSON without a real change on Letterboxd) → Track B.
- A new user with a large watchlist takes tens of minutes to first-sync and you were asked to
  improve it → Track C.
- You were asked to protect custom-list ordering/cap/merge invariants with tests → Track D.
- You resume campaign work from a previous session: read [Campaign status](#campaign-status), pick
  the highest-ranked OPEN track, start at its Phase 0.

## When NOT to use

- A production instance is misbehaving right now → `watchlistarr-debugging-playbook` (symptom trees).
- You need the story of a past incident (shas, root causes) → `watchlistarr-failure-archaeology`.
- You need system invariants or the module map → `watchlistarr-architecture-contract`.
- You need Letterboxd selectors/URLs/RSS details → `letterboxd-scraping-reference`.
- You need Radarr contract details (payload shape, StevenLuParser) → `radarr-integration-reference`.
- You are ready to commit/push/release → `watchlistarr-change-control`. This skill never replaces it.

## Campaign rules (read once)

1. **Derive before you implement.** Every solution below lists derivation obligations — numbers you
   must measure or prove first. A fix shipped without its derivation is how the cooldown revert
   happened (feature `23fec33` reverted 33 minutes later by `c8991da` because the mechanism did not
   explain the observations — full story in `watchlistarr-failure-archaeology`; method lesson in
   `watchlistarr-research-methodology`).
2. **The Radarr payload is sacred.** Any change to served JSON shape, URL scheme, or 404 semantics
   is a breaking change (major bump) and must update `scripts/smoke.py` asserts in the same commit.
   Enforced by `watchlistarr-change-control`.
3. **Never hit live Letterboxd from tests.** Tests use `respx` mocks and `tests/fixtures/`;
   `scripts/smoke.py` runs with `LETTERBOXD_OFFLINE=true` (`config.py:47`, `client.py:64-65`).
4. **House etiquette** (`.claude/rules.md:78`): min ~2s between requests, and *never* parallelize
   requests against the same Letterboxd account.
5. All work on branch `dev`. All promotion via [Promotion protocol](#promotion-protocol).

**Instance-dependent values.** Commands below use `$BASE` and the SQLite file:

```bash
BASE="http://localhost:${HTTP_PORT:-8080}"   # compose default 8080; the :8088 QC caveat → watchlistarr-run-and-operate
DB="data/watchlistarr.db"                    # default DATABASE_URL; inside the container it is /data/watchlistarr.db (Dockerfile:15,20)
```

Derive yours: `grep -h HTTP_PORT .env docker-compose*.yml 2>/dev/null` and
`grep -h DATABASE_URL .env 2>/dev/null` (absent → defaults above). See `watchlistarr-run-and-operate`.

---

## TRACK A — Letterboxd anti-bot resilience (rank 1) — OPEN

Problem: rate limiting is **per `LetterboxdClient` instance**, each job constructs its own client,
so N concurrent jobs legally hit Letterboxd at N × 0.5 req/s. A Cloudflare 403 is a hard stop with
no recovery playbook: the request fails, the job errors, and every other job keeps hammering on its
own schedule.

### Phase A0 — Baseline (measure before touching anything)

**A0.1 — Confirm the per-instance limiter.**

```bash
grep -n "Lock\|sleep\|MIN_INTERVAL" src/watchlistarr/services/letterboxd/client.py
```

Expect exactly these anchors (as of 2026-07, v1.5.2):
- `client.py:15` — `MIN_INTERVAL_SECONDS = 2.0` (module constant, per-request spacing)
- `client.py:33` — constructor accepts `min_interval_seconds` override (tests pass `0`)
- `client.py:46` — `self._lock = asyncio.Lock()` → **per-instance**, not module-level
- `client.py:67` — `async with self._lock:` wraps wait + request (strict serialization *within* one client)
- `client.py:83` — the rate-limit `asyncio.sleep(wait)`
- `client.py:96` — the 5xx retry backoff sleep (1s→2s, max 3 attempts, `client.py:85-100`)

If the anchors moved → re-read the file; if a module-level lock/semaphore already exists → Track A
solution A1 may already be landed; check `git log --oneline -- src/watchlistarr/services/letterboxd/client.py`
and update [Campaign status](#campaign-status) before proceeding.

**A0.2 — Enumerate client instantiation sites.**

```bash
grep -rn "LetterboxdClient(" src/ scripts/
```

Expect **exactly 6 runtime sites in `src/` + 2 in `scripts/`** (as of 2026-07, v1.5.2 — the campaign
briefing predicted 5; the real count is 6):

| # | Site | Created by | Concurrency source |
|---|---|---|---|
| 1 | `src/watchlistarr/scheduler.py:260` | `_with_user` — rss / discovery / films-backstop jobs | one per job run |
| 2 | `src/watchlistarr/scheduler.py:279` | `_with_watchlist` — watchlist incr/full jobs | one per job run |
| 3 | `src/watchlistarr/scheduler.py:310` | `_with_list` — list incr/full jobs | one per job run |
| 4 | `src/watchlistarr/services/onboarding.py:99` | `_initial_run` — whole onboarding uses ONE client | one per added user |
| 5 | `src/watchlistarr/services/onboarding.py:167` | `_sync_single_list` — toggle-on immediate sync | one per toggle |
| 6 | `src/watchlistarr/routes/api/v1.py:509` | `POST /api/v1/users` username validation | one per add-user request |
| 7–8 | `scripts/backfill_imdb.py:28`, `scripts/backfill_ratings.py:29` | manual one-shots | operator-invoked |

If you see a different count → the code moved; redo the table with real `file:line` before any design.

**A0.3 — Derive the concurrency ceiling from scheduler state.**

Scheduler jobs are the only automatic concurrency source. Job count formula (verify against
`scheduler.py:92-174`): `jobs = 2 + 3U + 2W + 2L` where the constant 2 = `rotation-tick` +
`prune-scrape-runs` (no Letterboxd traffic), U = users, W = users with watchlist enabled,
L = enabled regular lists. **Letterboxd-hitting jobs = 3U + 2W + 2L.**

```bash
curl -s -X POST "$BASE/admin/scheduler/sync"          # → {"jobs": N}
sqlite3 "$DB" "SELECT COUNT(*) FROM users;"
sqlite3 "$DB" "SELECT COUNT(*) FROM lists WHERE source_type='watchlist' AND enabled=1;"
sqlite3 "$DB" "SELECT COUNT(*) FROM lists WHERE source_type='list' AND enabled=1;"
```

Expect: `N == 2 + 3U + 2W + 2L`. Worked example: 1 user, watchlist disabled, 2 enabled lists →
**exactly 9 job ids**. Instance-dependent: derive via the four commands above. If the formula does
not hold → `scheduler.sync_jobs()` changed; re-read `scheduler.py:83-176` before designing A1.
`max_instances=1, coalesce=True` (`scheduler.py:186-195`) only serializes *per job id* — different
jobs run freely in parallel, each with its own client. Also note `trigger_now` (`scheduler.py:69-74`,
used by `POST /admin/refresh/{job_id}`) awaits inline and **bypasses** `max_instances=1`.

**A0.4 — Measure observed requests/min from the Activity buffer.**

```bash
curl -s "$BASE/api/v1/activity/download" | grep -F "film.resolve" | cut -c1-16 | sort | uniq -c | sort -rn | head
```

This buckets film-page fetches per minute (line format `ISO-ts LEVEL [src] message`,
`log_buffer.py:99-104`; first 16 chars = `YYYY-MM-DDTHH:MM`). Expect during a single full sync:
**≤ 30/min** (2s spacing ⇒ hard ceiling 30 req/min per client). **Any sustained bucket > 30/min is
proof of multiple clients in parallel** — the Track A smoking gun.
Caveats (all verified): successful GETs are NOT logged by `client.py` (only `letterboxd.forbidden`
:92 and `letterboxd.retry_5xx` :95); `film.resolve` (`film_resolver.py:115`) logs one line per
film-page fetch only; watchlist page fetches log `watchlist.full_sync.page` (`watchlist.py:105-111`);
list-page fetches log nothing per-page → this metric **undercounts** total traffic. Buffer holds only
the last 2000 lines (`log_buffer.py:35`) and resets on restart.

Count recent 403s (input for A2 decision):

```bash
curl -s "$BASE/api/v1/activity/download" | grep -c "letterboxd.forbidden"
sqlite3 "$DB" "SELECT COUNT(*) FROM scrape_runs WHERE status='error' AND error LIKE '%403%' AND started_at > datetime('now','-7 day');"
```

Expect 0 on a healthy instance (instance-dependent). Record the numbers in your working notes —
they gate the A1/A2/A3 choice.

### Phase A1 — Ranked solution menu (derive, then implement ONE at a time)

**A1 — Module-level global rate limiter (rank 1, do first).** One `asyncio.Lock` (or
`asyncio.Semaphore(1)`) + shared last-request timestamp at module scope in `client.py`, keyed by
host, so all client instances serialize through one 2s-spaced pipeline.
Derivation obligations BEFORE writing code:
- State the max concurrent Letterboxd-hitting tasks from A0.3 (+ onboarding/toggle/add-user tasks,
  sites 4–6) for the owner's instance. If it is provably ≤ 1, A1 buys nothing — stop and pick A3.
- Design around the test seams: `tests/unit/letterboxd/test_client.py:67` (`0`) and `:80` (`0.05`),
  and `tests/integration/conftest.py:25` (`0`) construct clients with tiny `min_interval_seconds`. A global
  limiter MUST still honor the per-instance override (e.g. global state keyed per event loop with
  injectable interval), or the whole suite slows to 2s/request and CI times out.
- Prove it with a test: extend `tests/integration/test_scrape_concurrency.py` (exists; currently
  proves two concurrent scrapers don't deadlock SQLite) with a case running two *distinct*
  `LetterboxdClient` instances concurrently against `respx` routes whose side effects record
  `time.monotonic()`; assert consecutive request timestamps are ≥ the configured interval apart.
  Use a small interval (e.g. 0.05s like `test_client.py:76-85`), never 2s, to keep the suite fast.

**A2 — 403 circuit breaker / request budget (rank 2, needs A1's shared state).** Today a 403 is
logged and raised immediately with no retry (`client.py:91-93`); the failing job's audit row goes to
`error`, the list gets `last_sync_status='error'` (`scheduler.py:241-247`), and every other job
retries on its normal interval — i.e. during a Cloudflare block the instance keeps knocking.
Breaker: on 403, open a shared circuit for a backoff window; while open, every `get()` fails fast
with a distinct exception; close after the window (optionally after one probe request).
Derivation obligations:
- From A0.4: how many 403s, how clustered? Zero observed 403s = no evidence to size a window; ship
  A1+A3 first and leave A2 as designed-but-unshipped (label it candidate).
- Prove the anti-flap interaction is safe (it is — verify and state it): a scrape that raises never
  reaches the write session (`lists.py:70-97`, `watchlist.py:134-168`: all HTTP happens before
  `async with factory() as session`), so failed scrapes cannot increment `pending_removal_count`
  or mass-remove. A breaker therefore only delays data freshness, never corrupts state.
- Decide breaker scope: 403 from `/film/{slug}/` mid-`resolve_films` aborts the whole sync (fine —
  audited as error), but the breaker must also stop the *other* jobs, which is exactly why the
  state must be module-level, not per-client.

**A3 — Jittered intervals to de-synchronize job starts (rank 3, cheap, independent).**
`sync_jobs()` re-adds all jobs at the same instant (`scheduler.py:89`), so equal-interval
`IntervalTrigger`s fire in phase — e.g. all `list-incr-*` at 6h boundaries simultaneously.
APScheduler's `IntervalTrigger` accepts a `jitter` seconds parameter; `scheduler.py:186-195` does
not set it today.
Derivation obligations:
- Show phase alignment on the live instance first: `curl -s "$BASE/api/v1/dashboard"` → `upcoming`
  (5 next jobs); several identical `next_run_time` values = confirmed.
- Pick jitter ≪ smallest interval (default smallest is `RSS_INTERVAL` 15m; jitter of 60–120s is
  proportionate). State the numbers.
- Note: jitter alone does NOT bound concurrency (long full syncs still overlap) — it complements
  A1, never replaces it.

### FENCED OFF — do not do these

- **Per-scrape cooldowns** (`lists.min_sync_interval` etc.): tried and reverted in 33 minutes
  (migration 0007 `23fec33` → migration 0008 `c8991da`, both inside v1.4.0). It misdiagnosed the
  churn source (serve-time rating re-sort, not scrape frequency). Details:
  `watchlistarr-failure-archaeology`. Do not reintroduce.
- **Lowering `MIN_INTERVAL_SECONDS` below 2.0** or parallelizing per-account (`.claude/rules.md:78`).
- Retrying 403s. 403 means "back off", not "try harder".

### Track A gates

| Gate | Command | Pass condition |
|---|---|---|
| A-G1 tests | the 5 CI steps ([Promotion protocol](#promotion-protocol)) | all green, incl. the new serialization test |
| A-G2 serialization proof | `uv run pytest tests/integration/test_scrape_concurrency.py -v` | new test asserts inter-request gap ≥ interval across two clients |
| A-G3 smoke | `uv run python scripts/smoke.py` | green — Radarr asserts untouched (payload not payload-adjacent here) |
| A-G4 QC | rebuild per `watchlistarr-run-and-operate`; rerun A0.4 during a manual `POST $BASE/admin/refresh/<job_id>` | no bucket > 30/min with two jobs forced concurrently |

Promotion: behavior-changing, payload untouched → **minor bump** via `watchlistarr-change-control`.

---

## TRACK B — Zero-flap guarantee (rank 2) — OPEN

"Flap" = an item leaving and re-entering the served Radarr JSON without a real Letterboxd change.
The anti-flap removal rule (canonical form in `watchlistarr-architecture-contract`,
code `services/scrape/anti_flap.py:88-154`) protects against *transient scrape noise* — but three
candidate work items remain, each with an evidence obligation.

### B1 — Dead `custom_lists.enabled` flag (worked example of blast-radius derivation)

Fact (verified 2026-07): `CustomList.enabled` defaults to `True` (`models/custom_lists.py:56`); the
Radarr endpoint `GET /lists/{slug}/` never checks it (`routes/api/radarr.py:39-51`); raw lists and
watchlists DO 404 when disabled (`radarr.py:75,100`). No endpoint writes it:

```bash
grep -rn "enabled" src/watchlistarr/routes/api/v1.py | grep -vi rotation
```

Expect only reads: serialization (`v1.py:164,299`), dashboard counts (`v1.py:128,176,379,382`), and
the *raw-list* toggle (`v1.py:569-578` — writes `lists.enabled`, not `custom_lists.enabled`).

This is a **candidate change**. Classification: a 404-semantics change to the Radarr surface is
**breaking by default** per `watchlistarr-change-control` and needs **explicit owner sign-off**
before the bump decision is made. The blast-radius derivation below is the case you PRESENT at
sign-off (arguing for a lesser bump) — it is NOT a pre-granted exception.

**Blast-radius derivation (the worked example — copy this reasoning style for every "is it
breaking?" argument you bring to sign-off):** default is `True`; there is no setter in any API
route or UI form; therefore no reachable state has `enabled=False` unless someone hand-edited the
DB — wiring the 404 changes behavior for zero API-reachable states, *conditional on verifying
the live instance*:

```bash
sqlite3 "$DB" "SELECT COUNT(*) FROM custom_lists WHERE enabled=0;"
```

Expect **0 rows with count 0**. Instance-dependent: a nonzero count means a hand-disabled list that
would start 404ing to Radarr the moment you ship — the argument for a lesser bump collapses.

Decision gate: (a) wire the 404 into `radarr.py:39-51` mirroring `radarr.py:100` (touches 404
semantics of the Radarr surface → breaking by default, owner sign-off decides the bump —
Promotion protocol step 3; **add a disabled-custom-list 404 assert to `scripts/smoke.py` in the
same commit** either way), and optionally (b) add a toggle endpoint + UI so the flag is settable
(separate commit; see `watchlistarr-config-and-flags` for what is UI-settable today).
Shipping (a) without (b) is acceptable — the flag stays DB-edit-only but at least it is honored.

### B2 — Selector-drift tripwires (empty-scrape guard)

**Current behavior, verified in code (2026-07, v1.5.2) — this is the risk statement:**
if Letterboxd changes its HTML so `parse_list_items` finds zero
`div.react-component[data-item-slug]` nodes but the HTTP response is still 200, a full sync
proceeds with `all_slugs == []`, `resolved == {}`, and then (`lists.py:60-105`,
`watchlist.py:118-177`):

1. every existing item is "absent from the scrape" → `reconcile_full_scrape` runs on all of them;
2. items in the owner's `watched_films` are **deleted immediately** (`anti_flap.py:120-127`);
3. items confirmed on `/films/` page 1 via the ad-hoc backstop are **deleted immediately**
   (`anti_flap.py:130-144`);
4. everything else gets `pending_removal_count += 1` and is deleted once the counter reaches the
   effective flap threshold (`anti_flap.py:146-154`; default `FLAP_CONFIRM_SCRAPES=3`, per-list
   override can be as low as 0/1);
5. `film_count` is overwritten to 0 (`lists.py:96`) and — the nasty part —
   `last_sync_status = SUCCESS` (`lists.py:95`). **Selector drift mass-deletes while reporting
   success.** There is no guard comparing scrape size against existing items. (Not ambiguous;
   verified line by line.)

Sibling silent failure: `parse_total_pages` returns 1 when `div.pagination` is missing
(`services/letterboxd/lists.py:56-58`) → a paginated list silently scrapes page 1 only; page-1
items upsert fine, every item from the missing pages drains through the counter over the next
`threshold` full syncs.

Candidate tripwires (design decisions to make, then implement):
- **Empty-scrape abort**: in `sync_list_full`/`sync_watchlist_full`, if `len(resolved) == 0` and the
  list currently has > 0 `list_items`, raise before the write session (the audit will record the
  error; anti-flap state untouched). Edge case to decide: a list the owner *genuinely emptied* would
  then never sync to empty — require N consecutive empty results, or an admin override, and document it.
- **Shrink tripwire**: warn/abort when `len(all_slugs)` < X% of the discovery-reported
  `lists.film_count`. Caveat you must design around: full sync overwrites `film_count` with
  `len(resolved)` (`lists.py:96`), so after the first drifted sync the reference value is gone —
  compare before overwrite, or persist the discovery-reported count separately.
- Evidence obligation: an integration test in `tests/integration/test_scrape_lists.py` feeding an
  HTML fixture with zero item nodes into a list that has existing items; assert items survive and
  the run errors. Fixture recipe: `watchlistarr-proof-and-analysis-toolkit`.

Gate: test proving "0-item scrape on a populated list removes nothing and aborts loudly" + the 5 CI
steps + smoke (payload untouched → minor).

### B3 — Chained-list staleness bound

A custom list sourcing another custom list reads the source's **materialized** `custom_list_items`
(`services/custom_lists.py:94-116`), refreshed only by: PUT edit (`recalculate`, `v1.py:941`),
rotation tick when rotation enabled (rotate swaps a FIFO batch only — it never evicts items that no
longer qualify), or snapshot refresh (bound = `snapshot_interval`). A chained list with neither
rotation nor snapshot **never refreshes after creation** — unbounded staleness. Evidence obligation
before doing anything:

```bash
sqlite3 "$DB" "SELECT custom_list_id, source_custom_list_id FROM custom_list_sources WHERE source_custom_list_id IS NOT NULL;"
```

Expect: 0 rows → no chains exist on this instance → B3 is theoretical here; document the bound in
`.claude/data-model.md` terms and move on. Rows present → measure real staleness
(`SELECT id, slug, last_rotated_at, last_snapshot_at, rotation_enabled, snapshot_interval FROM custom_lists;`)
and decide: include chained lists in `rotation_tick` recalculation (behavior change, minor) vs.
document "chained lists require rotation or snapshot to stay fresh" as an operating rule.

---

## TRACK C — First-sync latency (rank 3) — OPEN

### C0 — Baseline arithmetic (from code, no measurement needed to start)

Client spacing is 2s/request (`client.py:15`). A first full sync of a list with N films, all unknown
to the DB, costs:

```
T ≈ (P + N + B) × 2s
P = list pages fetched (1 request per page; items/page is Letterboxd's choice —
    instance-dependent: derive from the `page_items` field of `watchlist.full_sync.page`
    log lines during a real sync)
N = film-page fetches: 1 per slug that misses the resolver cache (first sync: all of them)
B = 1 if the ad-hoc /films/ backstop fires (first sync: 0 — no existing items can "disappear")
```

Dominated by N: a 1000-film watchlist ≈ 2000s ≈ **33 minutes**. Onboarding
(`services/onboarding.py:89-146`) full-syncs **every discovered list including the watchlist,
sequentially, through one client** — total first-sync time is the sum over all lists (deduped by the
resolver cache, next paragraph).

**Already in code — do not rebuild (verified):**
- Batch resolution exists: `resolve_films` (`film_resolver.py:75-166`) does one short read session,
  pure-HTTP middle phase, one short write session.
- **Within-call dedup: yes** — `unique_slugs = list(dict.fromkeys(slugs))` (`film_resolver.py:94`).
- **Cross-list dedup within one onboarding run: effectively yes, via the DB** — each list's write
  session commits before the next list starts, so a slug resolved for list 1 cache-hits for list 2…
  **except** the cache condition requires `imdb_id IS NOT NULL AND letterboxd_avg_rating IS NOT NULL`
  (`film_resolver.py:108`). Films genuinely lacking an IMDb link or rating are re-fetched for every
  list that contains them, on every sync, forever. So "skip film-page fetch when slug seen in
  another list same run" is already ~true; the real leak is the strict cache condition.

Measure the leak before optimizing it:

```bash
sqlite3 "$DB" "SELECT COUNT(*) FROM films WHERE imdb_id IS NULL OR letterboxd_avg_rating IS NULL;"
```

Expect: small relative to `SELECT COUNT(*) FROM films;` (instance-dependent). Each such film costs
2s per containing list per sync.

### Solution menu (ranked; each with derivation obligations)

- **C1 — Resumable initial run.** Onboarding steps are already failure-isolated (`_run_step`,
  `onboarding.py:73-86`) and a restart mid-run is repaired lazily by scheduler ticks — but a restart
  re-syncs lists that already finished. Change: skip lists with `last_sync_status='success'` on a
  re-run/re-add. Derive first: how much does a restart actually waste? Count per-list durations from
  `scrape_runs` (`SELECT target_id, status, started_at, ended_at FROM scrape_runs WHERE source IN ('list','watchlist') ORDER BY started_at DESC LIMIT 20;`).
- **C2 — Order the onboarding queue.** `_collect_lists` (`onboarding.py:61-70`) returns lists in DB
  order. Sync the watchlist first (it is what most users point Radarr at), then smallest lists
  first. At onboarding time all lists are `enabled=False` (new user), so "enabled first" only
  matters for re-added users. Pure ordering change, no new requests — cheap win, still needs a test
  asserting the order.
- **C3 — Split the resolver cache condition.** Cache-hit on `imdb_id IS NOT NULL` alone; enrich
  ratings only when some consumer needs them (rating sort/filters). Derive first: the leak count
  above, and which custom lists actually use `min_rating`/`max_rating`/`rating_desc`
  (`SELECT slug, sort_order, min_rating, max_rating FROM custom_lists;`). Touches identity
  enrichment — re-read `watchlistarr-architecture-contract` first.
- **C4 — Parallelize across users** (different accounts ⇒ etiquette-compatible). **HARD DEPENDENCY:
  safe ONLY after Track A's A1 global limiter is merged** — without it, parallel users multiply
  total req/s exactly like the bug Track A exists to fix. If A1 serializes globally at 2s, C4 buys
  nothing until the limiter is made per-account-aware; that redesign belongs to Track A, not here.

### FENCED OFF

- Parallelizing requests against the same Letterboxd account (`.claude/rules.md:78`).
- Lowering the 2s spacing to make syncs faster.

Gate: the 5 CI steps + smoke; before/after timing evidence from `scrape_runs` for the same seed user
(record numbers in the commit message). Behavior-changing → minor.

---

## TRACK D — Custom-list correctness (rank 4) — OPEN

The 2026-05 correctness cluster (duplicate positions `72b2f10`, incremental position corruption
`25aa6e5`, ignored sorts `844c5bf`, non-truncating `max_items` `4a28431`, PUT clobbering `6e84292` —
stories in `watchlistarr-failure-archaeology`) defines the invariant set to protect. `position` has
no UNIQUE constraint (`models/custom_list_items.py:27`) — only code discipline
(`_reindex_positions`, `services/custom_lists.py:348-372`) maintains it, so regressions are silent.

### The invariant set (probe each on the live DB — expect 0 rows from every probe)

```bash
# I1 — no duplicate positions within a custom list
sqlite3 "$DB" "SELECT custom_list_id, position, COUNT(*) c FROM custom_list_items GROUP BY custom_list_id, position HAVING c>1;"
# I2 — positions contiguous 0..N-1
sqlite3 "$DB" "SELECT custom_list_id FROM custom_list_items GROUP BY custom_list_id HAVING MIN(position)!=0 OR MAX(position)!=COUNT(*)-1;"
# I3 — max_items honored in materialized state
sqlite3 "$DB" "SELECT cl.id, cl.max_items, COUNT(i.tmdb_id) n FROM custom_lists cl JOIN custom_list_items i ON i.custom_list_id=cl.id GROUP BY cl.id HAVING cl.max_items IS NOT NULL AND n>cl.max_items;"
```

(Defense-in-depth: serve time also applies `LIMIT max_items` — `services/radarr.py:50-51`.)

- **I4 — PUT merge semantics** (`v1.py:906-936`): absent field → keep current; explicit `null` →
  clear. Documented quirks any test must encode, not "fix" accidentally: `_parse_optional_int`
  maps `0` → `None` (`v1.py:650-665` — you cannot set `maxItems=0`); a non-null `yearLastN`
  clears `min_year`/`max_year` (`v1.py:917-925`); `rotationBatchSize` falls back to `1`
  (`v1.py:928-930`).
- **I5 — snapshot precedence over rotation**: when `snapshot_interval` is set, the tick runs
  `refresh_snapshot`, never `rotate` (`services/custom_lists.py:544-549`); serve order is frozen to
  persisted `position` in snapshot mode even for `rating_desc` (`services/radarr.py:41-49`).

### Property-based test harness (candidate — not yet buildable as-is)

`hypothesis` is **NOT a dependency** (verified: absent from `pyproject.toml:9-35`). Adding it is a
change-control decision: `uv add --group dev hypothesis` + `uv.lock` in the same commit, via
`watchlistarr-change-control` (see `watchlistarr-build-and-env` for lockfile discipline). Until
then, the same properties can run as a plain pytest loop over `random`-generated op sequences with a
fixed seed.

Properties as executable pseudocode (target file: `tests/integration/test_custom_list_properties.py`):

```python
# state machine over one CustomList seeded with K films across 2 source lists
ops = st.lists(st.sampled_from([
    ("put", partial_payload),        # random subset of {maxItems, sortOrder, minRating,
                                     #  yearLastN, rotationEnabled, rotationInterval,
                                     #  snapshotInterval, sources}
    ("rotate_tick", None),           # await rotation_tick(session)  — advance last_rotated_at
                                     #  / last_snapshot_at into the past first to force firing
    ("source_shrink", n),            # delete n list_items from a source list (simulates anti-flap)
]), min_size=1, max_size=30)

for op in ops:
    apply(op)
    # INVARIANTS — after EVERY op:
    assert no_duplicate_positions()            # I1: len(positions) == len(set(positions))
    assert positions == list(range(len(items)))  # I2 contiguity (after ORDER BY position)
    if cl.max_items is not None:
        assert len(items) <= cl.max_items      # I3
    if op is put:
        for field not in payload: assert unchanged(field)   # I4 merge
        # generator rule: never emit 0 for int fields — 0 means None (v1.py:650-665)
    if cl.snapshot_interval is not None and op is rotate_tick:
        assert refresh_snapshot_ran_not_rotate()            # I5 (spy/log capture)
```

Build ops through the real code paths (HTTP PUT via the FastAPI test client, or
`recalculate`/`rotate`/`refresh_snapshot` directly with a session from
`tests/integration/conftest.py`), never by writing rows directly — the invariants live in the code
paths. Repro recipes and fixture construction: `watchlistarr-proof-and-analysis-toolkit`.

Gate: I1–I3 probes return 0 rows on the live DB before AND after; new property test green under the
5 CI steps; smoke untouched (pure test addition → patch; adding the hypothesis dep → chore, same
commit as its lockfile).

---

## Promotion protocol

Every track's change lands through `watchlistarr-change-control` — no exceptions, no shortcuts:

1. Branch `dev` only; merge to `main` only when the owner explicitly asks.
2. Before push, run the house pre-push gate locally (`.claude/rules.md:21-29` — note it lints
   `scripts` too, which CI does NOT; campaign work creates new `scripts/` files, so never use the
   narrower CI scope locally; the full local/CI asymmetry table is in `watchlistarr-validation-and-qa`):

```bash
uv sync --frozen
uv run ruff check src tests scripts && \
uv run ruff format --check src tests scripts && \
uv run mypy src && \
uv run pytest -q && \
uv run python scripts/smoke.py
```

3. If the change is payload-adjacent (anything touching served JSON, Radarr URL surface, or 404
   semantics — Track B1 qualifies): update `scripts/smoke.py` asserts **in the same commit**;
   payload/URL/404 semantic changes are breaking → major bump by default. Any argument for a
   lesser bump (e.g. B1's blast-radius derivation) requires explicit owner sign-off via
   `watchlistarr-change-control` BEFORE merging.
4. Commit message in **Spanish**, conventional-commit typed (fix → patch, feat/behavior → minor,
   breaking → major; details in `watchlistarr-change-control`).
5. After each commit: push, then rebuild the local QC copy and eyeball it
   (`docker compose -f docker-compose.dev.yml up -d --build`; port truth in
   `watchlistarr-run-and-operate`).
6. Update the [Campaign status](#campaign-status) table below in the same commit that changes a
   track's state.

## Campaign status

| Track | Rank | Problem | Status | Last update |
|---|---|---|---|---|
| A — anti-bot resilience | 1 | per-instance rate limit; no 403 playbook | **OPEN — not started** | 2026-07 |
| B — zero-flap guarantee | 2 | dead `custom_lists.enabled`; no empty-scrape guard; chain staleness | **OPEN — not started** | 2026-07 |
| C — first-sync latency | 3 | ~2s × N film pages; sequential onboarding | **OPEN — not started** | 2026-07 |
| D — custom-list correctness | 4 | invariants unguarded by property tests | **OPEN — not started** | 2026-07 |

## Provenance and maintenance

Everything above was verified by reading the repo at v1.5.2 (2026-07, HEAD `4439c17`). Numbers that
age are marked instance-dependent with their derivation command. Re-verify before trusting:

| Fact | Re-verify with |
|---|---|
| Per-instance lock, 2s spacing, 403 no-retry | `grep -n "Lock\|MIN_INTERVAL\|403" src/watchlistarr/services/letterboxd/client.py` |
| 6 client instantiation sites in `src/` | `grep -rn "LetterboxdClient(" src/ \| wc -l` |
| Job formula `2 + 3U + 2W + 2L` | `grep -n "_add(" src/watchlistarr/scheduler.py` (2 global + 3 per-user + 2 watchlist + 2 per-list blocks) |
| `max_instances=1` per job; `trigger_now` bypass | `grep -n "max_instances\|await job.func" src/watchlistarr/scheduler.py` |
| No empty-scrape guard; SUCCESS stamped after 0-item full sync | read `src/watchlistarr/services/scrape/lists.py:60-105` |
| Anti-flap immediate-delete branches vs counter | `grep -n "session.delete\|pending_removal_count" src/watchlistarr/services/scrape/anti_flap.py` |
| `custom_lists.enabled` unread by Radarr route | `grep -n "enabled" src/watchlistarr/routes/api/radarr.py` (expect exactly :75,:100 — raw routes only; none in :39-51) |
| Resolver dedup + cache condition | `grep -n "fromkeys\|imdb_id is not None" src/watchlistarr/services/scrape/film_resolver.py` |
| `parse_total_pages` silent 1 | `grep -n "return 1" src/watchlistarr/services/letterboxd/lists.py` |
| hypothesis not a dep | `grep -n hypothesis pyproject.toml` (expect no output) |
| 5 CI steps | `grep -n "run:" .github/workflows/ci.yml` |
| Etiquette rule | `grep -n "paralelizar" .claude/rules.md` |
| `position` not UNIQUE | `grep -n "position" src/watchlistarr/models/custom_list_items.py` |

When a track closes (merged + verified on QC), flip its status row and prune any phase the fix made
obsolete — a campaign doc that describes fixed problems as live is worse than no doc.
