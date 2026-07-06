---
name: watchlistarr-research-methodology
description: How investigation is done in this project — the evidence bar for root-cause claims, the fill-in refutation worksheet, the predict-numbers-before-running worksheet, and the idea lifecycle (proposal → evidence → adoption or documented retirement/tombstone). Use when you are about to explain WHY something happens (Radarr churn, mystery removals, slow syncs, phantom crashes), before shipping a fix for a symptom whose mechanism you have not proven, before running any measurement or experiment, or when proposing/retiring a feature idea. NOT for known symptoms with existing decision trees → use `watchlistarr-debugging-playbook`. NOT for the measurement instruments themselves (fixtures, respx, EXPLAIN, bisect) → use `watchlistarr-proof-and-analysis-toolkit`. NOT for looking up what happened in a past incident → use `watchlistarr-failure-archaeology`. NOT for landing an accepted change → use `watchlistarr-change-control`.
---

# watchlistarr — Research methodology

This skill owns HOW you investigate unknown mechanisms in this project. It exists because this
repo once shipped a fix for the wrong mechanism and had to revert it 33 minutes later (§3). The
method below would have caught it before the commit.

## When to use

- You observed a symptom (Radarr output churning, items vanishing, syncs slow, intermittent
  crash) and are about to write down "the cause is X".
- You are about to ship a fix and cannot yet state the mechanism in one sentence that explains
  every observation.
- You are about to run a measurement, benchmark, or experiment (job counts, sync durations,
  payload sizes, query timings).
- You are proposing a new feature/approach, or deciding to abandon one.
- A bug you "fixed" happened again, or a problem "fixed itself".

## When NOT to use

- The symptom is already in a known decision tree (sync stuck, spinner, 403, locked DB, Radarr
  empty, flicker, UI blank, migration failure) → `watchlistarr-debugging-playbook`. Come back
  here when the tree exits with "unknown mechanism".
- You need an instrument (fixture-based repro, respx, `EXPLAIN QUERY PLAN`, git bisect, SQLite
  lock analysis) → `watchlistarr-proof-and-analysis-toolkit`. This skill decides WHAT to prove;
  that one shows HOW.
- You want the record of a past incident → `watchlistarr-failure-archaeology`.
- Evidence is complete and you are ready to implement → `watchlistarr-change-control`.

## 1. THE EVIDENCE BAR (law)

> A root-cause explanation is **accepted** only when:
>
> 1. **ONE mechanism explains ALL observations** — including the **negatives**: things that did
>    NOT happen but WOULD have happened if the hypothesis were true.
> 2. It has **survived a self-assigned adversarial refutation attempt**: you explicitly asked
>    "what would disprove this?" and then **checked**.
>
> Until both hold, the explanation is a hypothesis. Hypotheses do not get fixes shipped for
> them. No exceptions for "obvious" causes — the cooldown revert (§3) looked obvious too.

Corollaries:

- "The fix made the symptom stop" is NOT acceptance. Symptoms stop for unrelated reasons
  (interval timing, cache, restart, Radarr's own poll cycle). You must show the mechanism.
- Two mechanisms each explaining half the observations = zero accepted explanations. Keep
  digging or explicitly document a two-cause finding with evidence for each.
- A negative you cannot check (no logs, no `scrape_runs` rows, state overwritten) is a gap —
  say so in the worksheet, do not silently skip the row.

### The refutation worksheet (fill in before claiming root cause)

Copy this into your scratch notes and fill every cell. An empty cell means you are not done.

```markdown
## Hypothesis H: <one sentence: MECHANISM, not symptom — "X causes Y via Z">

### Observations (positive)
| # | Observation | Predicted by H? (yes/no/partially) | Checked how (command / file:line / log line) |
|---|---|---|---|
| 1 |  |  |  |

### Negatives (what did NOT happen — would H have predicted it?)
| # | Non-observation | If H were true, would this have happened? | Checked how |
|---|---|---|---|
| 1 |  |  |  |

### Refutation attempts (what would disprove H? did I check?)
| # | Disproving evidence that would exist if H is false | Looked for it? | Found? |
|---|---|---|---|
| 1 |  |  |  |

### Verdict
- [ ] ONE mechanism explains ALL rows above (incl. negatives)
- [ ] At least one serious refutation attempt executed, H survived
- Verdict: ACCEPTED / REJECTED / NEEDS-MORE-EVIDENCE (state the missing row)
```

Rules for filling it:

- Observations are facts with provenance (a log line, a DB row, a diff, a Radarr screenshot) —
  never memories of facts.
- The Negatives table is the one people skip and the one that catches wrong mechanisms. Ask:
  "what ELSE would be broken if H were true?" and "who is NOT affected who should be?"
- A refutation attempt must be capable of failing. "I re-read the code and still agree with
  myself" is not one. "I queried `scrape_runs` for the window between the two Radarr polls" is.

## 2. Where the evidence comes from

The worksheet needs instruments; those live in `watchlistarr-proof-and-analysis-toolkit`
(fixture repro, respx, SQLite inspection, bisect). Typical evidence sources in this repo:

| Question | Source |
|---|---|
| Did a scrape run in window T? | `scrape_runs` table (`started_at`, `ended_at`, `status`) |
| What did Radarr actually receive? | `curl` the route + `ETag` comparison — see `radarr-integration-reference` |
| What does the serve path compute? | Read `src/watchlistarr/services/radarr.py` (it is a pure SELECT — DB-authoritative) |
| When did behavior X start? | `git log -S` / bisect against fixtures |
| What did the scheduler do? | `scheduler.synced` / `anti_flap.*` structlog lines |

## 3. THE central cautionary tale: the scrape-cooldown revert

This is the one skill where this incident is retold in full, because it is the worked example
of the evidence bar failing. For the incident-record version (and all other incidents), see
`watchlistarr-failure-archaeology`.

### What happened (verified in git, as of 2026-07, v1.5.2)

1. **Observed symptom**: the output Radarr received from "top-N by rating" custom lists kept
   changing between polls — items reordered and rotated in/out ("churn").
2. **Hypothesized mechanism**: "we are scraping Letterboxd too often, so the data keeps
   changing." Plausible-sounding; never tested against the observations.
3. **Shipped fix** — commit `23fec33` (2026-05-23 18:46): a hard per-list sync cooldown.
   Migration `0007_min_sync_interval` added `lists.min_sync_interval` and
   `users.watchlist_min_sync_interval`; scheduler wrappers gained a `cooldown_skip` guard; the
   UI got a "Min interval between syncs" field; 78 lines of tests were written. All of it built
   on an unproven mechanism.
4. **Reality**: the churn came from the **serve path**, not the scrape path. Two mechanisms,
   both orthogonal to scrape frequency: (a) `serialize_custom_list` re-sorted by *current*
   rating on **every request** — any rating drift reordered the payload with zero scrapes in
   between; (b) `rotate` cycled items every `rotation_interval`. No scrape cooldown, however
   long, could stop either.
5. **Revert** — commit `c8991da` (2026-05-23 19:19, **33 minutes later**): dropped the whole
   feature (migration `0008_swap_cooldown_for_snapshot` removes the 0007 columns) and shipped
   the correct fix: opt-in **snapshot mode** (`custom_lists.snapshot_interval` /
   `last_snapshot_at`) — the list is materialized by persisted `position` and the serve path
   stops re-sorting by rating when `snapshot_interval is not None`
   (`src/watchlistarr/services/radarr.py:41-49`). Both commits landed inside v1.4.0; the
   cooldown never existed in any released version. (The CHANGELOG's claim that the cooldown was
   "introduced in v1.3.0" is contradicted by git — `23fec33` postdates the v1.3.0 release.)
6. **Permanent scars**: migrations 0007+0008 remain in the chain as a dead add-then-drop pair
   (forward-only — do not "clean it up"), and the "force sync" button that motivated putting
   the guard in the scheduler wrappers was never built.

### The worksheet, run retroactively — watch it catch the bug before the commit

```markdown
## Hypothesis H: frequent scraping causes Radarr output churn
   (mechanism: each scrape changes list_items, so each Radarr poll sees different data)

### Observations (positive)
| # | Observation | Predicted by H? | Checked how |
|---|---|---|---|
| 1 | RATING_DESC custom-list payload order differs between two Radarr polls | partially — only if a scrape ran in between | scrape_runs between the two poll timestamps |
| 2 | Items rotate in/out of capped custom lists over hours | no — rotation_tick does this on its own clock | rotation_interval vs scrape schedule |

### Negatives
| # | Non-observation | If H were true, would this have happened? | Checked how |
|---|---|---|---|
| 1 | Order changed between two polls with NO scrape in between | H predicts order is STABLE with no scrape → H FAILS this row | scrape_runs empty for the window, yet ETag differed |
| 2 | Raw user lists (position-ordered) did NOT churn | H predicts ALL list types churn equally — they share the scrape schedule | compare raw-list ETag stability vs custom-list |

### Refutation attempts
| # | Disproving evidence | Looked for? | Found? |
|---|---|---|---|
| 1 | A payload diff with zero scrape_runs in the window | YES → found | H is dead |
| 2 | Serve path recomputing order per request | read services/radarr.py | YES: ORDER BY current rating |

### Verdict: REJECTED — mechanism does not explain negatives 1–2.
   Real mechanism must live in the serve path (per-request re-sort) and rotation.
```

Row "Negatives #1" is the kill shot: **does scrape frequency explain that the ordering changed
between two polls with no scrape in between? NO.** One `scrape_runs` query — under a minute of
work — refutes the hypothesis that instead cost a migration, a UI field, 78 lines of tests, a
revert commit, and two permanent dead migrations. That is the entire argument for this skill.

## 4. Predict-numbers-before-running worksheet

Before ANY measurement or experiment, write down — in this order, BEFORE running anything:

```markdown
## Prediction
- Number I expect: <value ± tolerance>
- Derivation (mechanism-based, cite file:line for every constant):
- Falsification threshold: "if the measured value is outside <range>, my model of the
  mechanism is wrong and I stop to find out why BEFORE using the measurement."
```

A measurement without a prior prediction cannot surprise you, and unsurprising measurements
teach nothing. If the number comes back outside the threshold, that is a finding — feed it
into a §1 worksheet; do not shrug and re-run.

### Worked micro-example (a): expected scheduler job count

**Mechanism** (read `src/watchlistarr/scheduler.py:83-176`, `sync_jobs()` — remove-all,
re-add from DB state):

- 2 global jobs, always: `rotation-tick`, `prune-scrape-runs` (lines 92-105).
- 3 jobs per user row, **unconditional** (enabled or not): `rss-{uid}`, `discovery-{uid}`,
  `films-backstop-{uid}` (lines 107-136).
- 2 more per user **only if that user's watchlist row is enabled**: `watchlist-incr-{uid}`,
  `watchlist-full-{uid}` (line 137 gate; enabled state read via `_watchlist_enabled_by_user`,
  lines 222-238).
- 2 per **enabled** list of `source_type == LIST`: `list-incr-{list_id}`, `list-full-{list_id}`
  (lines 156-174; the enabled+type filter is in `_enabled_lists_by_user`, lines 198-219 —
  disabled lists get NO jobs).

**Formula** (as of 2026-07, v1.5.2):

```
jobs = 2 + 3·U + 2·W + 2·L
  U = all rows in users (regardless of anything)
  W = users whose watchlist list-row is enabled
  L = enabled lists with source_type = 'list'
```

**Prediction for a concrete state**: 2 users; user A has watchlist enabled + 3 enabled lists;
user B has watchlist disabled + 1 enabled list + 2 disabled lists.
Expect `2 + 3·2 + 2·1 + 2·4 = 18`. Falsification: any other value.

**Verify**: `POST /admin/scheduler/sync` returns `{"jobs": N}` (`routes/api/admin.py:19-25`),
or read the `scheduler.synced` log line (`scheduler.py:176`). If N ≠ 18, your model of the DB
state or of the formula is wrong — stop and find which, before trusting anything downstream.

### Worked micro-example (b): expected duration of a full list sync

**Mechanism** (read `src/watchlistarr/services/scrape/lists.py:44-97`,
`services/scrape/film_resolver.py:94-117`, `services/letterboxd/client.py:15,63-83`):

- Page fetches: sequential, one per list page. Letterboxd serves **28 items/page** — that is a
  live-Letterboxd fact documented in `.claude/letterboxd-lists.md:109`, NOT a code constant;
  test fixtures are trimmed to ~3 items so do not count fixtures. → `ceil(L / 28)` requests.
- Film-page fetches: one `GET /film/{slug}/` per slug that is NOT cache-satisfied. Cache hit
  requires the film row to exist **with both** `imdb_id` and `letterboxd_avg_rating` non-NULL
  (`film_resolver.py:108`). → `F` requests, where F = unknown-or-incomplete films.
- Possibly +1 fetch of `/{user}/films/` — only when the scrape has unexplained disappearances
  (`services/scrape/anti_flap.py:67-77`).
- All requests go through ONE `LetterboxdClient` with a per-instance lock and
  `MIN_INTERVAL_SECONDS = 2.0` (`client.py:15,46,67-71`) — spacing is measured from the
  previous response's completion, so each request adds `max(2.0, gap) + latency`. Note the
  rate limit is **per client instance** and each scheduler job builds its own client
  (`scheduler.py:260,279,310`) — concurrent jobs do NOT share the budget.

**Formula** (as of 2026-07, v1.5.2):

```
requests N ≈ ceil(L/28) + F (+1)
duration  ≥ 2.0·(N−1) seconds; practical estimate ≈ N × (2 s + page latency)
```

**Prediction for a concrete state**: fresh DB, 642-item list, all films unknown →
N ≈ 23 + 642 = 665 → ≥ 22 min, ~25-28 min with real latency. History corroborates: the
initial sync of a 642-film watchlist held ~25 minutes in the "database is locked" incident
(`321b8d1`/`b7a44d2`, v1.0.2) — full story in `watchlistarr-failure-archaeology`.
Falsification: a full sync of that shape finishing in 5 minutes means your F is wrong (films
were already cached) — or someone changed the rate limit, which you must then investigate.

## 5. Idea lifecycle

Every idea in this project moves through exactly one of two terminal states:

```
proposal → evidence gathering (worksheets §1 + §4) → decision
        → ADOPTED   — implemented and landed via `watchlistarr-change-control`
        → RETIRED   — documented tombstone; never silently dropped
```

**A retired idea gets a tombstone entry** in `watchlistarr-failure-archaeology` (its
"reverted/reworked" section): what the idea was, why it was retired, and what evidence would
be needed to re-open it. A "tombstone" here = a written record that an idea is dead and why.

> **Rule: silence is not retirement.** An undocumented dead idea WILL be re-proposed by a
> future session that has no memory of why it died, and will burn the same tokens rediscovering
> the same refutation. If you decide against an idea after real evidence gathering, write the
> tombstone in the same session.

Current tombstones (as of 2026-07, v1.5.2) — one line each; full entries in
`watchlistarr-failure-archaeology`:

| Idea | Why dead | Evidence |
|---|---|---|
| Per-list scrape cooldown | Wrong mechanism for Radarr churn (§3); replaced by snapshot mode | `23fec33` → `c8991da`, migrations 0007/0008 |
| Global `settings` DB table + `/settings` screen | Replaced by per-entity nullable overrides + env defaults | `a967bbd`, migration 0002; see `watchlistarr-config-and-flags` |
| HTMX + Pico UI | Replaced by React 18 SPA ~12 hours after the MVP (554a808 09:18 → 434e250 20:07 / 72ff656 21:29, same day) | `58c94ab` → `434e250`/`72ff656` |
| Predefined combined endpoints (`/all/...`) + `Sublist` model | Replaced by multi-source Custom Lists (intentional breaking change, pre-1.0) | `58c94ab`, migration 0003 |

Do not re-propose any of these without NEW evidence that invalidates the recorded reason.

## 6. When to escalate from quick-fix to investigation

A quick fix (patch the symptom, move on) is acceptable for cosmetic and clearly-local issues.
The following triggers make a full §1 worksheet **mandatory** before any fix ships:

| Trigger | Why |
|---|---|
| Symptom touches the Radarr payload or removals | **The payload is sacred** — Radarr auto-adds and can mass-affect a library; wrong fixes here have blast radius. See `radarr-integration-reference` |
| Any `UNIQUE`-constraint crash | Historically the worst bug class in this repo (`films.letterboxd_slug` / `films.imdb_id`); a naive fix corrupts identity — see `watchlistarr-failure-archaeology` |
| "It fixed itself" | It did not. The mechanism moved out of view (interval timing, cache, restart) and will return; find it while the trail is warm |
| Second occurrence of a "fixed" bug | The first fix treated a symptom. The accepted-mechanism bar was never met — go back to §1 |

## 7. How this composes with sibling skills

| Skill | Division of labor |
|---|---|
| `watchlistarr-debugging-playbook` | Known symptoms with known decision trees. Its trees exit into THIS skill when the mechanism is unknown. |
| `watchlistarr-proof-and-analysis-toolkit` | The instruments (fixtures, respx, EXPLAIN, bisect, lock analysis). This skill decides what must be proven; that one executes the proof. |
| `watchlistarr-failure-archaeology` | The archive: full incident records and the tombstone registry that §5 writes into. |
| `watchlistarr-hardening-campaign` | Pre-derived campaigns over the four live problems, with gate numbers already computed via §4-style derivations. |
| `watchlistarr-change-control` | The only exit for ADOPTED ideas — no accepted finding ships except through its gates. |

## Provenance and maintenance

Every load-bearing fact above, with a one-line re-verification command (run from repo root):

| Fact | Re-verify |
|---|---|
| Cooldown commit + 33-min revert | `git log --format='%h %ad %s' --date=iso --no-walk 23fec33 c8991da` |
| Migrations 0007/0008 dead pair | `ls alembic/versions/ \| grep -E '0007\|0008'` and read both docstrings |
| Serve-time re-sort gated by snapshot mode | `grep -n "snapshot_mode\|RATING_DESC" src/watchlistarr/services/radarr.py` (expect lines ~41-49) |
| Scheduler job formula (2 + 3U + 2W + 2L) | `grep -n '_add(' src/watchlistarr/scheduler.py` and check the `if watchlist_enabled` gate + `enabled.is_(True)` filter in `_enabled_lists_by_user` |
| `{"jobs": N}` probe | `grep -n 'scheduler/sync' -A6 src/watchlistarr/routes/api/admin.py` |
| 2.0 s rate limit, per-instance | `grep -n 'MIN_INTERVAL_SECONDS\|asyncio.Lock' src/watchlistarr/services/letterboxd/client.py` |
| One client per scheduler job | `grep -n 'LetterboxdClient(settings)' src/watchlistarr/scheduler.py` |
| Film-page fetch cache condition (imdb_id AND rating) | `grep -n 'imdb_id is not None and' src/watchlistarr/services/scrape/film_resolver.py` |
| +1 films-page fetch only on unexplained disappearances | `grep -n 'candidates' src/watchlistarr/services/scrape/anti_flap.py` |
| 28 items/page (doc-sourced, live-Letterboxd fact) | `grep -n '28' .claude/letterboxd-lists.md` — re-confirm against live Letterboxd if scrape math stops matching |
| Tombstone commits | `git log --oneline --no-walk a967bbd 58c94ab 434e250 72ff656` |

If any command's output no longer matches this file, update the affected section in the same
commit as the code change — stale methodology docs are how the CHANGELOG ended up claiming the
cooldown shipped in v1.3.0.
