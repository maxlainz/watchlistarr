---
name: watchlistarr-docs-and-writing
description: Doc map, language policy, house writing style, and THE standing-errata table for watchlistarr. Use when writing or updating ANY documentation (README, CHANGELOG, .claude/*.md, skills), writing a commit message or CHANGELOG entry, deciding which doc to read or trust for a topic, checking whether a doc claim is known-wrong before repeating it (errata E1-E45 live here and ONLY here), figuring out which docs and skills a code change must update, or defining a skill's "Provenance and maintenance" section. Keywords - doc drift, stale docs, wrong docs, errata, language policy, Spanish commits, English README, Keep a Changelog, doc-update triggers, provenance. NOT for debugging live behavior (use watchlistarr-debugging-playbook), NOT for branch/merge/release mechanics (use watchlistarr-change-control), NOT for full incident histories (use watchlistarr-failure-archaeology), NOT for README capability/feature claims and their claims→evidence table (use watchlistarr-research-frontier), NOT for the content of the Radarr/Letterboxd contracts themselves (use radarr-integration-reference / letterboxd-scraping-reference).
---

# watchlistarr — docs, writing style, and the standing errata

Ground rule for everything below: **code is ground truth**. Docs (including this skill) are derived views. When a doc and the code disagree, the code wins, and the disagreement belongs in the standing-errata table (§Errata) until the doc of record is fixed.

## When to use

- You are about to write or edit `README.md`, `CHANGELOG.md`, any `.claude/*.md`, or a skill — read the language policy and house style first.
- You changed code and need to know **which docs to touch and which skills to re-verify** — use the doc-update triggers table.
- You read a claim in a doc and want to know if it is trustworthy before acting on it or repeating it — check the doc map grade, then scan the errata table for that doc.
- You found a NEW doc-vs-code mismatch — append a row to the errata table (next free E-number) instead of silently working around it.
- You are writing a commit message, a CHANGELOG entry, or a release-summary merge message.
- You are authoring or updating a skill and need the provenance-discipline rules that all skills follow.

## When NOT to use

- Diagnosing a live problem (sync stuck, 403, empty Radarr list) → `watchlistarr-debugging-playbook`.
- Branching, merging to `main`, cutting a release, deciding if a change is breaking → `watchlistarr-change-control`.
- The full story of a historical incident → `watchlistarr-failure-archaeology`.
- What the Radarr JSON/URL contract actually is → `radarr-integration-reference`. What Letterboxd's HTML/RSS actually looks like → `letterboxd-scraping-reference`.
- Env-var truth tables → `watchlistarr-config-and-flags`.

## Doc map — reading order, authority, reliability

Read in this order when onboarding to a task. Grades as of 2026-07 (v1.5.2, HEAD `4439c17`): **verified-accurate** = drift audit found no material errors; **has-errata** = see listed IDs before trusting.

| # | Doc | Authoritative for | Grade (2026-07) | Update when you touch… |
|---|---|---|---|---|
| 1 | `CLAUDE.md` | Task routing (which doc to read), top-level house rules | has-errata: E27 (`:8088` claim); skills language carve-out not yet codified (§Language) | Any new doc/skill, any changed top-level rule |
| 2 | `.claude/rules.md` | Git/commit discipline, CI steps, language, typing (mypy strict), comments, style, scraping etiquette | has-errata: E1, E2, E3 (also references the phantom `settings` table at L48 — see E4 footnote) | CI workflow, lint/type config, coding conventions |
| 3 | `.claude/architecture.md` | Component map, high-level design, design decisions | has-errata: E9, E14, E15, E16, E17 | Components added/removed, major design decisions |
| 4 | `.claude/data-model.md` | Entities, columns, enums, identity model, Radarr URL surface | mostly verified (all tables/columns/PKs/enums confirmed against `models/*.py` + migrations 0001-0009); minor errata: E42, E43, E44, E45 | DB schema, migrations, endpoints that read/write state |
| 5 | `.claude/sync-strategy.md` | Scrape frequencies, anti-flap policy, which source updates what | has-errata: E16, E18, E19, E20 (E18/E19 are HIGH — do not trust its onboarding or per-user-settings sections) | Scheduling, scraping cadence, invalidation, anti-flap |
| 6 | `.claude/letterboxd-lists.md` | List scraping: discovery, selectors, pagination, TMDB resolution | selectors/URLs verified correct against parsers; errata: E37, E38, E39, E40 | List scraper, selectors, discovery |
| 7 | `.claude/letterboxd-rss.md` | RSS feed format, namespaces, item types, edge cases | GUID/dedup/parsing verified correct; errata: E26 (shared), E41 (framing: RSS does NOT trigger rotation) | RSS watcher, feed parsing |
| 8 | `.claude/radarr-custom-list.md` | Radarr JSON contract, headers, pitfalls | JSON contract + ETag behavior verified correct; errata: E34 (its "filters before serving" section is pre-multi-source), E35 | Radarr routes, payload shape, headers |
| 9 | `.claude/tech-stack.md` | Versions, repo layout, project config, Docker anatomy | has-errata — **heaviest drift of any doc**: E4-E13 (incl. PHANTOM `settings` table, wrong healthcheck, wrong job ids) | Dependencies, pyproject, Dockerfile, repo structure |
| 10 | `.claude/workflows.md` | Dev commands, Docker, deploy, merge flow, env-var table | has-errata — second heaviest: E1, E24-E29 (incl. two HIGH PHANTOMs: paste-a-list-URL flow, per-list Refresh button) | Dev/QC workflow, compose files, env vars |
| 11 | `.claude/versioning.md` | SemVer mapping, tag/Docker-tag matrix, release procedure | verified-accurate except E36; the v1.2.2 `uv.lock` pitfall it documents is real | Release procedure, CI publish jobs |
| 12 | `.claude/ui-features.md` | Page/action/form catalog; what is web-configurable vs env-only | mostly verified (its L121 env-only claim is CORRECT where sync-strategy.md E18 is wrong); errata: E21, E22, E23 | Any GUI page, action, or form |
| 13 | `README.md` (public) | End-user install/connect/troubleshoot | has-errata: E30 (HIGH — promises a nonexistent Refresh button), E31 | Any user-visible feature or URL |
| 14 | `CHANGELOG.md` (public) | Release history | verified-accurate for 1.5.x claims; one historical inaccuracy: the cooldown feature's "introduced in v1.3.0" claim is contradicted by git (same-release; see `watchlistarr-failure-archaeology`, incident 6) | Every feature/fix commit (under `[Unreleased]`) |

Routing rule: `CLAUDE.md`'s "Contexto" table decides which doc a task needs. Do not duplicate content across docs — each fact has one home; siblings cross-reference.

## Language policy

| Surface | Language | Source |
|---|---|---|
| Internal docs (`CLAUDE.md`, `.claude/*.md`) | Spanish | `rules.md:37` |
| Commit messages | Spanish, short | `rules.md:9` |
| `README.md`, `CHANGELOG.md` (public face) | English | `rules.md:38` |
| Code, identifiers, filenames, branches, env vars | English | `rules.md:39` |
| **`.claude/skills/`** | **English** | Carve-out, user-approved 2026-07 — see below |

**The skills carve-out (authority note).** Skills under `.claude/skills/` are written in **English** — user-approved 2026-07. As of 2026-07-02, `CLAUDE.md` and `rules.md` do NOT yet mention `.claude/skills/` at all (verified: `grep -n "skills" CLAUDE.md .claude/rules.md` returns nothing); a Phase-4 change will codify the carve-out in `CLAUDE.md`. **Until CLAUDE.md is updated, THIS skill is the authority for the carve-out.** When you re-verify this skill, run that grep: if it still returns nothing, flag that CLAUDE.md remains un-updated; once it matches, delete this authority note and defer to CLAUDE.md.

Do not "fix" language mismatches you were not asked to fix: the CHANGELOG was deliberately translated to English at v1.5.1 (`CHANGELOG.md:68-70`); pre-1.5.1 entries already in English are fine as-is.

## House style

### Commit messages

- Spanish, short, descriptive. Conventional prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `ci:`, `test:`) welcome but not mandatory (`rules.md:9`). They DO drive version bumps at release time (`versioning.md` mapping table) — prefer using them.
- Merge-to-`main` message must summarize **everything** new since the previous `main` commit (`CLAUDE.md`, `rules.md:7`).
- Release commit is exactly `chore(release): vX.Y.Z` touching 4 files (`versioning.md:59`). Release mechanics live in `watchlistarr-change-control` — do not improvise them from here.

### CHANGELOG

- Format: [Keep a Changelog 1.1.0] + SemVer, declared at `CHANGELOG.md:3-5`. Sections used: `### Added` / `### Changed` / `### Fixed` / `### Docs`.
- English, always (since v1.5.1; `CHANGELOG.md:68-70`, `versioning.md:56`).
- **Write the entry in the same feature/fix commit**, under `## [Unreleased]`. At release, the whole `[Unreleased]` block moves to `## [X.Y.Z] - YYYY-MM-DD` and a fresh empty `[Unreleased]` is created (`versioning.md:56`). Never backfill entries at release time from memory.
- Entry voice: past-tense factual, names the symptom and the fix, cites identifiers in backticks. Read the 1.5.1 block (`CHANGELOG.md:21-75`) as the exemplar — it explains WHY each fix mattered ("Radarr kept importing items from them"), not just what changed.

### README (public)

- Voice set by the v1.5.2 end-user rewrite (`9ca0f8a`; verified via `CHANGELOG.md:17-18`): **end-user only, docker-compose-first, plain `docker run` as the alternative, simple tone, NO development sections.** Second person, imperative ("Add this to your `docker-compose.yml`"), short feature bullets with bold leads, a Troubleshooting section of symptom bullets.
- Development/contributor content does not belong in the README — it lives in `.claude/`.
- Every URL, feature, and button named in the README must exist in the shipped UI. E30 is the cautionary example: the README promises a per-list Refresh button that does not exist. Before adding any capability claim, verify it against `static/src/` and the routes.
- Feature/capability bullets are additionally governed by THE CLAIMS-EVIDENCE RULE — no public capability claim without a named in-repo test or command; update the claims→evidence table in `watchlistarr-research-frontier` in the same commit.

### `.claude/` internal docs

- Dense, Spanish, tables-over-prose, heavy cross-referencing with anchor links (`[rules.md → CI](rules.md#...)`).
- Each doc opens with a one-line "read this before touching X" statement of scope.
- Keep the one-home-per-fact rule: if a fact needs to appear in two docs, one states it, the other links.
- After any major change to architecture, commands, or rules, update the affected `.claude/` doc **in the same PR** (`CLAUDE.md` rule).

### Skills (`.claude/skills/`)

- English. Imperative runbook voice ("Run X. Expect Y. If Z instead, go to §N."). Headings + tables + fenced commands; no narrative filler.
- YAML frontmatter with `name` (exact directory name) and a trigger-rich `description` including "NOT for X → use `sibling-skill`" disambiguation.
- Required sections: `## When to use`, `## When NOT to use`, `## Provenance and maintenance`.
- Commands copy-pasteable from repo root; prefer commands over frozen counts; date-stamp any stated number "(as of 2026-07, v1.5.2)".
- Cross-reference sibling skills by their exact directory names in backticks. One home per fact — skills included.

## Provenance discipline (binding for ALL skills)

This section defines the maintenance contract every skill in `.claude/skills/` follows:

1. **Every skill carries a `## Provenance and maintenance` section**: for each fact that can drift (a route, a flag, a formula, a line number, a count), one runnable one-line re-verification command, executable from repo root.
2. **Same-PR rule**: any PR that changes a fact guarded by a skill's provenance line MUST update that skill in the same PR. This is the same discipline as the `scripts/smoke.py`-in-the-same-commit rule (`CLAUDE.md`), extended to skills. Use the doc-update triggers table below to find which skills a change touches.
3. **Unfixable drift goes here**: if you find doc-vs-code drift you cannot fix in the current PR (out of scope, doc of record frozen, needs owner decision), add a row to the standing-errata table below with the next free E-number, and reference it by ID from wherever you hit it. Never restate a known erratum's content in another skill or doc — write "see E*n* in `watchlistarr-docs-and-writing`".
4. **Code is ground truth, always.** A skill or doc is never evidence against the code; it is a cache of the code that can go stale.
5. Anything you cannot verify by reading the repo: omit it or label it `(unverified)`.

## Doc-update triggers

Change class → docs of record to touch (same PR) → skills whose `## Provenance and maintenance` commands to re-run (and update if they fail).

| Change class | Docs to touch | Skills to re-verify |
|---|---|---|
| Radarr routes, payload shape, 404 semantics ("the Radarr payload is sacred" — breaking change; see `watchlistarr-change-control`) | `radarr-custom-list.md`, `README.md` URL table, `CHANGELOG.md`, `scripts/smoke.py` asserts (same commit) | `radarr-integration-reference`, `watchlistarr-architecture-contract`, `watchlistarr-validation-and-qa`, `watchlistarr-change-control` |
| Scheduling: job ids, intervals, new jobs | `sync-strategy.md` | `watchlistarr-run-and-operate`, `watchlistarr-config-and-flags`, `watchlistarr-architecture-contract` |
| DB schema, migrations, enums | `data-model.md` | `watchlistarr-architecture-contract`, `watchlistarr-proof-and-analysis-toolkit`, `watchlistarr-diagnostics-and-tooling` |
| Env vars, per-entity overrides, precedence | `workflows.md` env table, `ui-features.md` "NO está en GUI", `.env.example` | `watchlistarr-config-and-flags`, `watchlistarr-build-and-env` |
| Letterboxd selectors, URLs, RSS parsing, rate limiting | `letterboxd-lists.md` / `letterboxd-rss.md` | `letterboxd-scraping-reference`, `watchlistarr-debugging-playbook` |
| CI workflow, lint/type/test config | `rules.md` §CI, `workflows.md` | `watchlistarr-validation-and-qa`, `watchlistarr-change-control` |
| UI pages, actions, forms | `ui-features.md` | `watchlistarr-run-and-operate`, `watchlistarr-debugging-playbook` |
| Dependencies, toolchain, Dockerfile, compose | `tech-stack.md` | `watchlistarr-build-and-env` |
| Release/versioning procedure | `versioning.md`, `rules.md` §Versionado | `watchlistarr-change-control` |
| Anti-flap logic, identity resolution | `sync-strategy.md`, `data-model.md` | `watchlistarr-architecture-contract`, `radarr-integration-reference`, `watchlistarr-hardening-campaign` |
| Any user-visible feature | `README.md`, `CHANGELOG.md` `[Unreleased]` | `watchlistarr-docs-and-writing` (README claims) |

## Standing-errata table

> **Code is ground truth. Rows are REMOVED when the doc is fixed (record the fix date in the changelog row of this table's history section). Other skills must reference errata by ID instead of restating them.**
>
> A **Phase-4 pass is planned to fix most of these in the docs of record** — rows will be emptied then. **As of 2026-07-02, all 45 rows are still open.** Source audit: commit `4439c17` (one docs commit past v1.5.2). Numbering matches the original drift audit 1:1 (E*n* = finding #*n*).

Classes: **WRONG** (doc contradicts code) · **STALE** (was true, code moved on) · **MISSING** (code feature undocumented) · **PHANTOM** (doc describes something that does not exist). Severity: **HIGH** = following the doc leads you astray or lies to users; **MED** = wastes time / wrong mental model; **LOW** = cosmetic. The audit's five "informational" nits are normalized here as WRONG/LOW (E13, E23, E29, E40, E44).

All paths repo-relative. Run re-verify commands from `/home/user/watchlistarr`.

| ID | Class | Sev | Doc & location | Doc's claim | Code truth | Re-verify |
|---|---|---|---|---|---|---|
| E1 | WRONG | HIGH | `rules.md` §CI L13,24-28; `workflows.md` L76-80 | Local "reproduce CI" block lints `src tests scripts`, presented as the exact 5 CI steps | CI lints only `src tests` (`.github/workflows/ci.yml:35,38`); `scripts/` is never linted in CI — the asymmetry is a house rule, not CI parity | `grep -n "ruff" .github/workflows/ci.yml` |
| E2 | STALE | LOW | Same docs as E1 | Local pytest step is `uv run pytest -q` | CI runs `uv run pytest --cov=src/watchlistarr --cov-report=term` (`ci.yml:44`); same tests, different invocation | `grep -n "pytest" .github/workflows/ci.yml` |
| E3 | WRONG | MED | `tech-stack.md` L163 (descriptive claim); `rules.md` L78 (see note) | A per-domain semaphore + ≥2 s spacing serializes all Letterboxd requests | Rate limit is per-`LetterboxdClient` INSTANCE (`services/letterboxd/client.py:46-83`); 6 instantiation sites in `src/` (`scheduler.py:260,279,310`; `services/onboarding.py:99,167`; `routes/api/v1.py:509`) plus 2 in `scripts/` (`backfill_imdb.py:28`, `backfill_ratings.py:29`), so concurrent jobs DO hit Letterboxd in parallel; no global semaphore exists. NOTE: `rules.md` L78 ("never parallelize requests to the same account") is a PRESCRIPTIVE house rule the code does not yet enforce — the RULE remains binding (aspiration-vs-reality framing in `letterboxd-scraping-reference`; fix tracked in `watchlistarr-hardening-campaign` Track A) | `grep -rn "LetterboxdClient(" src/ scripts/` (expect exactly the 8 sites listed) |
| E4 | PHANTOM | HIGH | `tech-stack.md` L168-174 | A `settings(key,value,updated_at)` table seeded from env, read by the scheduler, written by the UI | No `settings` table: created in `alembic/versions/0001_initial.py:52`, DROPPED in `0002_settings_per_entity.py:25`; config = env (`config.py`) + nullable override columns resolved in `services/intervals.py` | `grep -n "drop_table" alembic/versions/0002_settings_per_entity.py` |
| E5 | WRONG | MED | `tech-stack.md` L138-139 | Startup initializes the `settings` table from env; jobs read intervals from it | Lifespan = logging → alembic upgrade → `init_engine` → `fail_interrupted_runs` → `JobScheduler(...).sync_jobs()` (`src/watchlistarr/main.py:45-71`); no settings-init step | `sed -n 45,71p src/watchlistarr/main.py` |
| E6 | WRONG | MED | `tech-stack.md` L151 | Job-id examples `rss-watcher`, `watchlist-incremental-<uid>` | Real ids: `rss-{uid}`, `discovery-{uid}`, `films-backstop-{uid}`, `watchlist-incr-{uid}`, `watchlist-full-{uid}`, `list-incr-{lid}`, `list-full-{lid}`, `rotation-tick`, `prune-scrape-runs` (`scheduler.py:93-174`); `POST /admin/refresh/{job_id}` needs the exact id | `grep -n "rotation-tick\|prune-scrape-runs\|watchlist-incr" src/watchlistarr/scheduler.py` |
| E7 | STALE | MED | `tech-stack.md` L152-155 | UI interval change updates the `settings` row then `scheduler.reschedule_job(...)` | Settings endpoint writes `users`/`lists` override columns then `sync_jobs()` = remove-all-and-re-add (`routes/api/v1.py:595-627`, `scheduler.py:83-89`); `reschedule` exists but no endpoint calls it | `grep -n "sync_jobs\|reschedule" src/watchlistarr/routes/api/v1.py src/watchlistarr/scheduler.py` |
| E8 | WRONG | MED | `tech-stack.md` L236 | `HEALTHCHECK ... CMD curl -fs http://127.0.0.1:8080/healthz` | Healthcheck is a python-urllib one-liner (`Dockerfile:23-24`); `curl` is NOT in the slim image — copying the doc's healthcheck yields a permanently unhealthy container | `grep -n "HEALTHCHECK" -A1 Dockerfile` |
| E9 | STALE | LOW | `tech-stack.md` L241; `architecture.md` L91 | `DATABASE_URL=sqlite+aiosqlite:///data/watchlistarr.db` (3 slashes, relative) | Container env is 4 slashes, absolute: `Dockerfile:15` `sqlite+aiosqlite:////data/watchlistarr.db`; `.env.example:6` concurs; 3-slash form is only the bare `config.py:45` local default | `grep -n "DATABASE_URL" Dockerfile .env.example; grep -in "database_url" src/watchlistarr/config.py` |
| E10 | STALE | LOW | `tech-stack.md` L40-67 | "Versiones congeladas" dependency block | Omits `greenlet ~= 3.1`, the `sqlalchemy[asyncio]` extra, `pytest-cov`, `types-beautifulsoup4` (`pyproject.toml:9-35`) | `sed -n 9,35p pyproject.toml` |
| E11 | MISSING | LOW | `tech-stack.md` L71-127 | Repo tree | Omits `services/intervals.py`, `services/onboarding.py`, `services/log_messages.py`, all `services/scrape/` submodules, `scripts/`, `.github/` | `ls src/watchlistarr/services/scrape/` |
| E12 | STALE | LOW | `tech-stack.md` L189-194 | Test stack "pytest + pytest-asyncio + respx"; coverage targets parsers ≥90% / orchestration ≥70% | Also `pytest-cov` + `types-beautifulsoup4` (`pyproject.toml:27-35`); NO coverage threshold is enforced anywhere (CI only prints `--cov-report=term`) | `grep -n "cov" .github/workflows/ci.yml pyproject.toml` |
| E13 | WRONG | LOW | `tech-stack.md` L106 (tree comment) | `admin.py # /admin/refresh, /admin/scheduler/sync` | Routes are `POST /admin/refresh/{job_id}` and `POST /admin/scheduler/sync` (`routes/api/admin.py:8,19`); `/admin/refresh` without a job id is 404/405 | `grep -n "@router" src/watchlistarr/routes/api/admin.py` |
| E14 | STALE | MED | `architecture.md` L52 | "Motor TBD (SQLite probable)" | Decision long settled: SQLite is canonical (`data-model.md:3`, `config.py:45`, WAL pragmas `db.py:21-30`) | `grep -n "TBD" .claude/architecture.md` |
| E15 | PHANTOM | MED | `architecture.md` L94 | "Primer arranque presenta el wizard" | No wizard exists; first run is a plain empty state (`static/src/pages/Users.jsx:71`); no wizard strings anywhere in `static/` | `grep -rni "wizard" src/watchlistarr/static/` (expect no matches) |
| E16 | WRONG | MED | `architecture.md` L48; `sync-strategy.md` L99,104 | Rotation/init inserts RANDOM rows from the eligible pool | Insertion honors `sort_order` via `_choose_from_pool` (`services/custom_lists.py:271-298`): RATING_DESC = top-N by rating, LETTERBOXD/REVERSE = source position; random ONLY when `sort_order=RANDOM`; used by init (L328), recalculate (L413,435), rotate (L479) | `grep -n "_choose_from_pool" src/watchlistarr/services/custom_lists.py` |
| E17 | STALE | LOW | `architecture.md` L36 | Incremental scrape = "O(2) fetches usando `/by/added-earliest/`" | True for list pages (`services/scrape/lists.py:106-121`: page 1 + last page) but each NEW slug costs one extra film-page fetch via `resolve_films` | `sed -n 100,130p src/watchlistarr/services/scrape/lists.py` |
| E18 | WRONG | HIGH | `sync-strategy.md` L138 | `users.rss_interval` / `films_backstop_interval` / `discovery_interval` etc. editable in the user-detail "Advanced" UI | No such UI or endpoint; the only settings endpoint is `POST /api/v1/users/{u}/lists/{id}/settings` (`routes/api/v1.py:595-627`) covering watchlist/list incr+full and `flap_confirm_scrapes`; `rss_interval`, `films_backstop_interval`, `discovery_interval` are scheduler-honored (`services/intervals.py`) but settable ONLY by editing the DB (`ui-features.md:121` has it right) | `grep -rn "rssInterval\|discoveryInterval\|filmsBackstop" src/watchlistarr/static/ src/watchlistarr/routes/` (expect no matches) |
| E19 | WRONG | HIGH | `sync-strategy.md` L121-130 | After add-user only discovery + films-backstop run; watchlist NOT auto-scraped; full sync happens per list on activation | `_initial_run` (`services/onboarding.py:89-146`) does ensure-watchlist-row → discovery → films-backstop → FULL SYNC of EVERY discovered list, watchlist included, while all stay `enabled=False`; toggle-on additionally kicks an immediate full sync (`routes/api/v1.py:578-591`); big scraping-cost implication | `sed -n 89,146p src/watchlistarr/services/onboarding.py` |
| E20 | MISSING | LOW | `sync-strategy.md` L106-108 | Recalculate on edit = remove disqualified + fill up to `max_items` | Also TRUNCATES surplus when `max_items` was reduced, choosing keepers per `sort_order`, and reindexes positions (`services/custom_lists.py:410-425`) | `sed -n 375,449p src/watchlistarr/services/custom_lists.py` |
| E21 | STALE | MED | `ui-features.md` L43 | Add-user launches `_initial_run_in_background` (ensure + discovery + backstop) | Function is `schedule_initial_run` → `_initial_run` (`services/onboarding.py:147-157,89`) and the run ALSO full-syncs every discovered list (see E19) | `grep -n "_initial_run\|schedule_initial_run" src/watchlistarr/services/onboarding.py src/watchlistarr/routes/api/v1.py` |
| E22 | MISSING | LOW | `ui-features.md` L114-122 | List of env-only vars | Missing `LETTERBOXD_OFFLINE` (`config.py:47`, `.env.example:10`) — blocks all Letterboxd HTTP, used by smoke | `grep -n "letterboxd_offline" src/watchlistarr/config.py` |
| E23 | WRONG | LOW | `ui-features.md` L116 | "`HTTP_PORT` — puerto del servidor web" | `Settings.http_port` (`config.py:42`) is never read by app code; the container always listens on 8080 (`Dockerfile:25`); `HTTP_PORT` only moves the host-side compose mapping / dev `--port` arg | `grep -rn "http_port" src/ scripts/` |
| E24 | PHANTOM | HIGH | `workflows.md` L31-38 | "Añadir una lista nueva": paste a public list URL in the UI; per-list sort order / max items / rotation | NONE of this exists: lists appear only via user discovery and are toggled on (`static/src/pages/Users.jsx`, `Lists.jsx`); no paste-URL input anywhere; sort/max/rotation are CUSTOM-LIST properties only (`models/custom_lists.py`) | `grep -rn "paste" src/watchlistarr/static/src/` (expect no matches) |
| E25 | WRONG | HIGH | `workflows.md` L41-44 | Radarr URL `http://<host>:<HTTP_PORT>/list/<list_id>`; Radarr path "Settings → Lists" | No `/list/{id}` route exists; real routes `GET /lists/{slug}/`, `GET /{username}/watchlist/`, `GET /{username}/{slug}/` (`routes/api/radarr.py:39,54,81`); Radarr path is Settings → Import Lists (`radarr-custom-list.md:18` has it right) | `grep -n "@router.get" src/watchlistarr/routes/api/radarr.py` |
| E26 | PHANTOM | HIGH | `workflows.md` L50-52; `letterboxd-rss.md` L166; README L112 | Per-list "Refresh" button in the UI; "CLI: TBD" | No per-list refresh control exists — the ⚙ Advanced panel has only interval/flap inputs + Save (`static/src/pages/Lists.jsx:93-130`; `data.jsx` has no refresh call); real mechanisms: toggle off→on = immediate full sync (`routes/api/v1.py:578-591`), or `POST /admin/refresh/{job_id}` (so "CLI: TBD" is stale too) | `grep -rn "refresh" src/watchlistarr/static/src/data.jsx; grep -n "@router" src/watchlistarr/routes/api/admin.py` |
| E27 | STALE | MED | `workflows.md` L55-68; `CLAUDE.md` | Dev QC stack runs on `:8088`; verify with `curl http://127.0.0.1:8088/healthz` | `docker-compose.dev.yml:8` maps `${HTTP_PORT:-8080}:8080` — default 8080; `:8088` holds only via the owner's uncommitted `.env` (`HTTP_PORT=8088`); on a fresh clone the documented probe hits the wrong port | `grep -n "ports" -A1 docker-compose.dev.yml; grep -n "HTTP_PORT" .env.example` |
| E28 | MISSING | LOW | `workflows.md` L111-127 | Env-var table | Missing `LETTERBOXD_OFFLINE` (default `false`, `config.py:47`); all other names/defaults match `config.py` exactly | `sed -n 42,58p src/watchlistarr/config.py` |
| E29 | WRONG | LOW | `workflows.md` L14 | `uv run uvicorn ... --port "$HTTP_PORT"` right after `cp .env.example .env` | `.env` is read by pydantic-settings, NOT exported to the shell — `$HTTP_PORT` is empty unless separately exported | `bash -c 'echo "$HTTP_PORT"'` (empty unless exported) |
| E30 | WRONG | HIGH | `README.md` L112 | "you can force a refresh from the list's ⚙ menu" | The ⚙ panel has no refresh action (see E26) — public-facing doc promising a nonexistent feature | `grep -rn "refresh" src/watchlistarr/static/src/pages/Lists.jsx` (expect no matches) |
| E31 | STALE | LOW | `README.md` L58 | Pin example `:1.5.1` | Current release is 1.5.2 (`pyproject.toml:3`, `src/watchlistarr/__init__.py`); example only | `grep -n "^version" pyproject.toml` |
| E32 | WRONG | MED | `.env.example` L12 | Frequencies are "modificables desde la GUI" after first boot | Env defaults are IMMUTABLE at runtime (no settings table, no endpoint touches them); GUI sets only per-list/per-watchlist incr/full/flap overrides; `RSS_INTERVAL`, `FILMS_BACKSTOP_INTERVAL`, `DISCOVERY_INTERVAL`, `ROTATION_TICK_INTERVAL` are env-only (`routes/api/v1.py:595-627`) | `grep -rn "rss_interval" src/watchlistarr/routes/` |
| E33 | STALE | MED | `.env.example` L7 | `USER_AGENT=watchlistarr/1.0.0 (+...)` | Real default derives from `__version__` = 1.5.2 (`config.py:46`); CHANGELOG 1.5.1 specifically fixed the 1.0.0 UA pin — anyone copying `.env.example` RE-PINS the UA at 1.0.0 | `grep -n "user_agent" src/watchlistarr/config.py` |
| E34 | STALE | HIGH | `radarr-custom-list.md` L142-150,152-154 | On `GET /list/<list_id>` watchlistarr applies sort order, `max_items`, watched-exclusion; one URL ↔ one `list_id` | Pre-multi-source model: raw user lists are served UNFILTERED, position-ordered, uncapped (`services/radarr.py:17-29`); sort/max/exclusions exist only for custom lists, materialized in `custom_list_items` (`serialize_custom_list` L32-56); no `/list/<id>` route; contradicts the same doc's own L35 | `sed -n 17,56p src/watchlistarr/services/radarr.py` |
| E35 | STALE | LOW | `radarr-custom-list.md` L137-139 | ETag/If-None-Match "debería" be supported (future work) | Already implemented: weak SHA-1 ETag + 304 on If-None-Match (`routes/api/radarr.py:26-36`, `services/radarr.py:64-65`); smoke asserts it | `grep -in "etag\|if-none-match" src/watchlistarr/routes/api/radarr.py` |
| E36 | WRONG | LOW | `versioning.md` L10 | MAJOR examples include endpoint "`/radarr/list/{id}` y la forma del JSON" | No `/radarr/...` route was ever registered; the stable surfaces are `/{user}/{slug}/`, `/{user}/watchlist/`, `/lists/{slug}/` (`routes/api/radarr.py`) | `grep -rn "radarr/list" src/` (expect no matches) |
| E37 | STALE | MED | `letterboxd-lists.md` L9 | Config input `LETTERBOXD_USER` (profile slug env var) | No such env var; users are added multi-user via the UI (`POST /api/v1/users`, `routes/api/v1.py:499`) | `grep -rn "LETTERBOXD_USER" src/ .env.example` (expect no matches) |
| E38 | STALE | MED | `letterboxd-lists.md` L245 | Pipeline step: on `GET /list/{list_id}` apply sort / max_items / watched-exclusion | Same drift as E34: wrong URL, and raw lists have NO serve-time policies | `grep -n "@router.get" src/watchlistarr/routes/api/radarr.py` |
| E39 | PHANTOM | LOW | `letterboxd-lists.md` L96,249 | Private lists: the UI "debe permitir" pasting a URL manually as fallback | Not implemented anywhere in the SPA or API (no manual-URL list creation); phrased as requirement but reads like a feature | `grep -rni "private\|manual" src/watchlistarr/static/src/` (expect no matches) |
| E40 | WRONG | LOW | `letterboxd-lists.md` L101 | Watchlist stored "con `type='watchlist'`" | Column is `source_type` (enum `source_type_enum`), value `watchlist` (`models/lists.py:28-34`); `data-model.md` uses the right name | `grep -n "source_type" src/watchlistarr/models/lists.py` |
| E41 | STALE | MED | `letterboxd-rss.md` L3,44-45,150 | RSS watch-event "dispara la rotación"; engine crosses `watched_events` against rotation-enabled lists and removes items | RSS poll only upserts `viewing_logs` + `watched_films` (`services/scrape/rss_watcher.py`); nothing is "triggered": raw-list removals happen in the anti-flap path of FULL scrapes (owner-watched → immediate, `anti_flap.py:118-127`); custom lists with `excluded_watchers` lose the film only at their next rotation/recalc; table is `viewing_logs`, not `watched_events` | `grep -n "rotation\|watched" src/watchlistarr/services/scrape/rss_watcher.py` |
| E42 | WRONG | LOW | `data-model.md` L54 | When relative filters are set, the back "fuerza esos absolutos a NULL" (implying both year AND added pairs) | True only for `min_year`/`max_year` (`routes/api/v1.py:847-853,917-925`); `added_after`/`added_before` are NEVER parsed by any endpoint — DB-only columns, honored by `_apply_filters` (L179-186) if hand-seeded | `grep -n "added_after\|addedAfter" src/watchlistarr/routes/api/v1.py` (expect no matches) |
| E43 | STALE | LOW | `data-model.md` L102 | "`resolve_film` re-resuelve... cuando `imdb_id` ya está, devuelve la fila cacheada sin tocar HTTP" | Function is `resolve_films` (batch, since v1.0.2); cache hit requires BOTH `imdb_id` AND `letterboxd_avg_rating` non-NULL (`services/scrape/film_resolver.py:106-111`, condition at :108) — rating-NULL rows re-fetch | `sed -n 103,120p src/watchlistarr/services/scrape/film_resolver.py` |
| E44 | WRONG | LOW | `data-model.md` L88 | "`/<user>/watchlist/` — watchlist del user (alias de `/<user>/watchlist/`)" — self-referential typo | Presumably meant "alias de `/<user>/<slug>/` con slug reservado"; route exists once (`routes/api/radarr.py:54`) | `sed -n 85,90p .claude/data-model.md` |
| E45 | MISSING | LOW | `data-model.md` entity table | `custom_lists.enabled` documented as a plain column | Flag is effectively DEAD: no endpoint toggles it, the Radarr route serves the custom list regardless (`routes/api/radarr.py:39-51` never checks it); it only filters the dashboard `customCount` (`v1.py:381-383`); raw lists DO 404 when disabled — treat as open candidate work | `grep -n "enabled" src/watchlistarr/routes/api/radarr.py` — expect exactly two hits (:75, :100 — the raw watchlist/list routes); no hit inside `custom_list_endpoint` (:39-51) confirms the flag is never checked for custom lists |

**Footnotes.**
- E4 also leaks into `rules.md:48` ("...vía env vars (`Settings` de Pydantic) o tabla `settings`") — same phantom, fix together in the Phase-4 pass.
- Tally as of 2026-07-02 (primary classification; several straddle WRONG/STALE): WRONG 18 · STALE 17 · MISSING 5 · PHANTOM 5. HIGH-severity rows to never propagate: E1, E4, E18, E19, E24, E25, E26, E30, E34.
- If a re-verify command's output no longer matches the "Code truth" column, the CODE moved — update the row (and the skills the doc-update triggers table points at), do not assume the doc became right.

### How to reference an erratum from elsewhere

Write: "doc X currently claims Y — wrong as of 2026-07, see E*n* in `watchlistarr-docs-and-writing`". Never copy the row's content into another skill or doc. (Skills written before this table use the generic form "see the standing errata table in `watchlistarr-docs-and-writing`" — acceptable until a later pass adds E-ids at each referencing site; until then, step 4 of the fix procedure below is best-effort — also grep for the doc path, not just the ID.)

### How to fix an erratum (Phase-4 pass or ad hoc)

1. Edit the doc of record so it matches the "Code truth" column (Spanish for `.claude/*.md`, English for README/CHANGELOG).
2. Run the row's re-verify command to confirm the code truth still holds before writing it into the doc.
3. DELETE the row from the table above and add a line to the history section below with the date and IDs fixed.
4. Grep the skill library for the ID (`grep -rn "E<n>" .claude/skills/`) and update any skill that referenced it.

### Table history

| Date | Change |
|---|---|
| 2026-07-02 | Table created from the doc-drift audit at commit `4439c17` (v1.5.2 + 1 docs commit). 45 rows, all open. Phase-4 doc-fix pass planned. |

## Provenance and maintenance

Run from repo root. If any check fails, update the corresponding section of this skill in the same PR.

- Doc inventory still matches the doc map: `ls .claude/*.md` (expect the 11 docs listed in the map, plus `skills/`).
- Language policy source lines: `sed -n 35,39p .claude/rules.md` (Spanish internal/commits, English README+CHANGELOG+code).
- Skills-in-English carve-out still uncodified: `grep -n "skills" CLAUDE.md .claude/rules.md` — no matches = this skill remains the authority and the Phase-4 CLAUDE.md change is still pending (flag it); matches = defer to CLAUDE.md and delete the authority note in §Language policy.
- Commit style: `sed -n 9p .claude/rules.md`. Release-commit shape: `grep -n "chore(release)" .claude/versioning.md`.
- CHANGELOG format declaration: `sed -n 1,7p CHANGELOG.md` (Keep a Changelog 1.1.0 + SemVer, `[Unreleased]` present). Move-at-release rule: `grep -n "Unreleased" .claude/versioning.md`.
- README voice anchor (v1.5.2 end-user rewrite): `grep -n "README rewritten" CHANGELOG.md`. Commit sha `9ca0f8a` — verified: `git show -s 9ca0f8a` ("docs(readme): reescritura end-user…", 2026-06-11).
- Errata rows: each row carries its own re-verify command — run the commands for any row you are about to rely on or fix. Spot-check anchors re-verified 2026-07-02: `ci.yml:35,38,44`, `routes/api/radarr.py:39,54,81`, `alembic/versions/0002_settings_per_entity.py:25`, `config.py:42,46,47`, `Dockerfile:23-24`.
- Current version for date-stamps: `grep -n "^version" pyproject.toml` (1.5.2 as of 2026-07).
- Skill-name cross-references still valid: `ls .claude/skills/` and compare against the names used in the doc-update triggers table.
