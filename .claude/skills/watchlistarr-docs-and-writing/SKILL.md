---
name: watchlistarr-docs-and-writing
description: Doc map, language policy, house writing style, and THE standing-errata table for watchlistarr. Use when writing or updating ANY documentation (README, CHANGELOG, .claude/*.md, skills), writing a commit message or CHANGELOG entry, deciding which doc to read or trust for a topic, checking whether a doc claim is known-wrong before repeating it (THE errata table lives here and ONLY here; E1-E45 are resolved history as of 2026-07-02, open table currently empty), figuring out which docs and skills a code change must update, or defining a skill's "Provenance and maintenance" section. Keywords - doc drift, stale docs, wrong docs, errata, language policy, Spanish commits, English README, Keep a Changelog, doc-update triggers, provenance. NOT for debugging live behavior (use watchlistarr-debugging-playbook), NOT for branch/merge/release mechanics (use watchlistarr-change-control), NOT for full incident histories (use watchlistarr-failure-archaeology), NOT for README capability/feature claims and their claims→evidence table (use watchlistarr-research-frontier), NOT for the content of the Radarr/Letterboxd contracts themselves (use radarr-integration-reference / letterboxd-scraping-reference).
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

Read in this order when onboarding to a task. Grades as of **2026-07-02** (v1.5.2 + docs commits; post-Phase-4 errata-fix pass): **verified accurate as of 2026-07-02 (post-errata-fix pass)** = every audit finding for that doc was fixed in the doc of record and re-verified against code on that date. Resolved finding IDs are kept in the history section below so old cross-references still resolve.

| # | Doc | Authoritative for | Grade | Update when you touch… |
|---|---|---|---|---|
| 1 | `CLAUDE.md` | **The router**: doc-layer reading order + a task→skill routing table for all 16 skills, top-level house rules; codifies the skills language carve-out (§Language) and the skill-provenance same-commit maintenance rule | verified accurate as of 2026-07-02 (post-errata-fix pass; rewritten as router same date — formerly E27) | Any new doc/skill, any changed top-level rule |
| 2 | `.claude/rules.md` | Git/commit discipline, CI steps, language, typing (mypy strict), comments, style, scraping etiquette | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E1, E2, E3-note, E4-footnote) | CI workflow, lint/type config, coding conventions |
| 3 | `.claude/architecture.md` | Component map, high-level design, design decisions | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E9, E14-E17) | Components added/removed, major design decisions |
| 4 | `.claude/data-model.md` | Entities, columns, enums, identity model, Radarr URL surface | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E42-E45; tables/columns/PKs/enums confirmed against `models/*.py` + migrations 0001-0009) | DB schema, migrations, endpoints that read/write state |
| 5 | `.claude/sync-strategy.md` | Scrape frequencies, anti-flap policy, which source updates what | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E16, E18-E20 — its onboarding and per-user-settings sections now match code) | Scheduling, scraping cadence, invalidation, anti-flap |
| 6 | `.claude/letterboxd-lists.md` | List scraping: discovery, selectors, pagination, TMDB resolution | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E37-E40; selectors/URLs verified against parsers) | List scraper, selectors, discovery |
| 7 | `.claude/letterboxd-rss.md` | RSS feed format, namespaces, item types, edge cases | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E26-shared, E41; GUID/dedup/parsing verified) | RSS watcher, feed parsing |
| 8 | `.claude/radarr-custom-list.md` | Radarr JSON contract, headers, pitfalls | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E34, E35; JSON contract + ETag behavior verified) | Radarr routes, payload shape, headers |
| 9 | `.claude/tech-stack.md` | Versions, repo layout, project config, Docker anatomy | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly the heaviest-drift doc, E4-E13) | Dependencies, pyproject, Dockerfile, repo structure |
| 10 | `.claude/workflows.md` | Dev commands, Docker, deploy, merge flow, env-var table | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly second-heaviest, E1, E24-E29) | Dev/QC workflow, compose files, env vars |
| 11 | `.claude/versioning.md` | SemVer mapping, tag/Docker-tag matrix, release procedure | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E36); the v1.2.2 `uv.lock` pitfall it documents is real | Release procedure, CI publish jobs |
| 12 | `.claude/ui-features.md` | Page/action/form catalog; what is web-configurable vs env-only | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E21-E23) | Any GUI page, action, or form |
| 13 | `README.md` (public) | End-user install/connect/troubleshoot | verified accurate as of 2026-07-02 (post-errata-fix pass; formerly E30, E31) | Any user-visible feature or URL |
| 14 | `CHANGELOG.md` (public) | Release history | verified-accurate for 1.5.x claims; one historical inaccuracy: the cooldown feature's "introduced in v1.3.0" claim is contradicted by git (same-release; see `watchlistarr-failure-archaeology`, incident 6) | Every feature/fix commit (under `[Unreleased]`) |

Routing rule: `CLAUDE.md` is the router (rewritten 2026-07-02) — its "Contexto de diseño" table decides which doc a task needs, and its "Enrutado tarea → skill" table decides which skill to start from. Do not duplicate content across docs — each fact has one home; siblings cross-reference.

## Language policy

| Surface | Language | Source |
|---|---|---|
| Internal docs (`CLAUDE.md`, `.claude/*.md`) | Spanish | `rules.md:37` |
| Commit messages | Spanish, short | `rules.md:9` |
| `README.md`, `CHANGELOG.md` (public face) | English | `rules.md:38` |
| Code, identifiers, filenames, branches, env vars | English | `rules.md:39` |
| **`.claude/skills/`** | **English** | `CLAUDE.md` §Idioma (codified 2026-07-02) |

**The skills carve-out.** Skills under `.claude/skills/` are written in **English** — user-approved 2026-07 and **codified 2026-07-02 in `CLAUDE.md`** (its "Idioma" rule: "las skills de `.claude/skills/` en inglés — excepción aprobada 2026-07"). `CLAUDE.md` is the authority; this skill only records the history (until that date, this skill was the sole written authority for the carve-out and flagged the gap).

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
- Every URL, feature, and button named in the README must exist in the shipped UI. E30 (fixed 2026-07-02) is the cautionary example: the README promised a per-list Refresh button that never existed. Before adding any capability claim, verify it against `static/src/` and the routes.
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

## Standing errata (open)

> **Code is ground truth. Rows are REMOVED when the doc is fixed (record the fix date in this table's history section and move the row to the resolved list below). Other skills must reference errata by ID instead of restating them.**
>
> Classes: **WRONG** (doc contradicts code) · **STALE** (was true, code moved on) · **MISSING** (code feature undocumented) · **PHANTOM** (doc describes something that does not exist). Severity: **HIGH** = following the doc leads you astray or lies to users; **MED** = wastes time / wrong mental model; **LOW** = cosmetic. Next free ID: **E46** (E1-E45 are resolved history — never reuse them).

**EMPTY as of 2026-07-02.** The Phase-4 doc-fix pass (2026-07-02) fixed all 45 open rows in the docs of record; each fix was verified by re-reading the fixed doc against the code truth. New doc-vs-code drift you cannot fix in the current PR goes here as a new row.

| ID | Class | Sev | Doc & location | Doc's claim | Code truth | Re-verify |
|---|---|---|---|---|---|---|
| — | | | *(no open errata)* | | | |

### Resolved errata (fixed 2026-07-02, Phase-4 pass)

History, not a live drift list — the docs of record now state the code truth for every row below. IDs are kept so pre-existing cross-references still resolve (numbering matches the original drift audit 1:1). The **code facts** behind several rows remain true and live on in the skills that own them (per-client rate limiting E3, dead `custom_lists.enabled` flag E45, DB-only override columns E18, no refresh button E26/E30, no coverage threshold E12, `HTTP_PORT` dead code E23) — only the doc-drift layer was closed.

- **E1** — `rules.md` §CI / `workflows.md`: local lint block was presented as exact CI parity; now documented as a deliberately stricter house gate (CI lints `src tests` only).
- **E2** — `rules.md` / `workflows.md`: CI pytest invocation now documented with `--cov=src/watchlistarr --cov-report=term`.
- **E3** — `tech-stack.md` (+ `rules.md` L78 note): rate limiting now documented as per-`LetterboxdClient`-instance with no global semaphore; `rules.md` keeps the no-parallelism rule explicitly as aspiration-not-yet-enforced.
- **E4** — `tech-stack.md`: phantom `settings(key,value,updated_at)` table removed (table was dropped in migration 0002; now noted as a retired candidate). The `rules.md:48` leak was fixed in the same pass.
- **E5** — `tech-stack.md`: startup lifespan sequence corrected (no settings-init step).
- **E6** — `tech-stack.md`: real scheduler job ids documented (`rotation-tick`, `prune-scrape-runs`, `rss-{uid}`, `watchlist-incr-{uid}`, …).
- **E7** — `tech-stack.md`: interval changes documented as override-column writes + `sync_jobs()` remove-all/re-add (no endpoint uses `reschedule`).
- **E8** — `tech-stack.md`: healthcheck documented as the python-urllib one-liner (no `curl` in the slim image).
- **E9** — `tech-stack.md` / `architecture.md`: container `DATABASE_URL` documented as 4-slash absolute; 3-slash form scoped to bare local dev.
- **E10** — `tech-stack.md`: dependency block completed (`greenlet`, `sqlalchemy[asyncio]`, `pytest-cov`, `types-beautifulsoup4`) and marked as convenience copy of `pyproject.toml`.
- **E11** — `tech-stack.md`: repo tree completed (`services/intervals.py`, `onboarding.py`, `log_messages.py`, `services/scrape/` submodules, `scripts/`, `.github/`).
- **E12** — `tech-stack.md`: test stack completed; "no coverage threshold enforced anywhere" stated.
- **E13** — `tech-stack.md`: admin route comment corrected to `POST /admin/refresh/{job_id}` + `POST /admin/scheduler/sync`.
- **E14** — `architecture.md`: "Motor TBD" replaced with SQLite-decided (+ WAL pragmas pointer).
- **E15** — `architecture.md`: first-boot wizard claim removed (plain empty state; wizard reframed as unimplemented candidate).
- **E16** — `architecture.md` / `sync-strategy.md`: rotation/init insertion documented as `sort_order`-honoring via `_choose_from_pool` (random ONLY with `sort_order=RANDOM`).
- **E17** — `architecture.md`: O(2)-fetch incremental claim qualified with the per-new-slug film-page fetch via `resolve_films`.
- **E18** — `sync-strategy.md`: `users.rss_interval`/`films_backstop_interval`/`discovery_interval` documented as scheduler-honored but DB-edit-only (no UI or endpoint writes them).
- **E19** — `sync-strategy.md`: onboarding documented as full pre-sync of EVERY discovered list, watchlist included, all `enabled=False` (+ toggle-on immediate full sync and the scraping-cost implication).
- **E20** — `sync-strategy.md`: recalculate-on-edit documented to also truncate surplus per `sort_order` and reindex positions when `max_items` shrinks.
- **E21** — `ui-features.md`: add-user flow corrected to `schedule_initial_run` → `_initial_run` including the full pre-sync of all discovered lists.
- **E22** — `ui-features.md`: `LETTERBOXD_OFFLINE` added to the env-only list.
- **E23** — `ui-features.md`: `HTTP_PORT` documented as host-side-mapping-only / dead code in app (container always listens 8080).
- **E24** — `workflows.md`: phantom paste-a-list-URL flow replaced by the discovery+toggle reality; per-list sort/max/rotation correctly scoped to custom lists; paste-URL reframed as unimplemented candidate.
- **E25** — `workflows.md`: Radarr URL corrected from `/list/<list_id>` to the three real routes; Radarr path corrected to Settings → Import Lists.
- **E26** — `workflows.md` / `letterboxd-rss.md` / `README.md`: phantom per-list "Refresh" button (and "CLI: TBD") removed; real mechanisms documented (toggle off→on immediate full sync, `POST /admin/refresh/{job_id}`).
- **E27** — `workflows.md` / `CLAUDE.md`: `:8088` QC-port claim replaced with "port = your `HTTP_PORT`; 8080 on a fresh clone; `:8088` is owner-uncommitted-`.env`-only".
- **E28** — `workflows.md`: `LETTERBOXD_OFFLINE` added to the env-var table.
- **E29** — `workflows.md`: `--port "$HTTP_PORT"` dev command replaced with an explicit port + warning that pydantic-settings reads `.env` but the shell does not.
- **E30** — `README.md` L112: nonexistent ⚙-menu refresh promise replaced with the real toggle-off/on guidance.
- **E31** — `README.md`: pin example bumped to `:1.5.2`.
- **E32** — `.env.example`: "modificables desde la GUI" comment replaced with the immutable-env + per-entity-override truth (env-only vars named).
- **E33** — `.env.example`: active `USER_AGENT=watchlistarr/1.0.0` pin removed — now a commented `x.y.z` example noting the default derives from the installed version. (Pre-2026-07 user copies of `.env` may still carry the pin — an operational nuance kept in `watchlistarr-config-and-flags` / `watchlistarr-build-and-env`.)
- **E34** — `radarr-custom-list.md`: pre-multi-source "filters before serving on `GET /list/<list_id>`" section replaced with the real raw-unfiltered vs custom-materialized serve semantics.
- **E35** — `radarr-custom-list.md`: ETag/If-None-Match documented as implemented (weak SHA-1 + 304, smoke-asserted), no longer "future work".
- **E36** — `versioning.md`: MAJOR-example endpoint `/radarr/list/{id}` replaced with the three real stable routes.
- **E37** — `letterboxd-lists.md`: `LETTERBOXD_USER` env-var input replaced with multi-user add via `POST /api/v1/users`.
- **E38** — `letterboxd-lists.md`: pipeline serve step corrected (raw lists served position-ordered with no serve-time sort/cap/exclusion).
- **E39** — `letterboxd-lists.md`: private-list manual-URL "debe permitir" requirement reframed as unimplemented candidate.
- **E40** — `letterboxd-lists.md`: `type='watchlist'` corrected to `source_type` (enum `source_type_enum`).
- **E41** — `letterboxd-rss.md`: "RSS dispara la rotación" framing replaced — poll only writes `viewing_logs`+`watched_films`; consumption is deferred (anti-flap on full scrapes; excluded-watcher custom lists at next rotation/recalc); `watched_events` corrected to `viewing_logs`.
- **E42** — `data-model.md`: relative-filter save semantics corrected (only `min_year`/`max_year` forced NULL; `added_after`/`added_before` are DB-only columns no endpoint parses).
- **E43** — `data-model.md`: `resolve_films` (batch) + both-fields-non-NULL cache condition documented.
- **E44** — `data-model.md`: self-referential watchlist-alias typo fixed ("caso especial de `/<user>/<slug>/` con el slug reservado `watchlist`").
- **E45** — `data-model.md`: `custom_lists.enabled` documented as a dead flag (default True, untoggleable, never checked by the Radarr route; open candidate work).

### How to reference an erratum from elsewhere

For an OPEN erratum, write: "doc X currently claims Y — wrong as of <date>, see E*n* in `watchlistarr-docs-and-writing`". For a RESOLVED one, write past tense: "doc X previously claimed Y (fixed 2026-07-02; E*n*)". Never copy a row's content into another skill or doc. When fixing, also grep for the doc path, not just the ID — older references may use the generic "see the standing errata table" form.

### How to fix an erratum (ad hoc)

1. Edit the doc of record so it matches the code truth (Spanish for `.claude/*.md`, English for README/CHANGELOG).
2. Run the row's re-verify command to confirm the code truth still holds before writing it into the doc.
3. MOVE the row from the open table to the resolved list (one line: ID — doc: what was fixed) and add a dated line to the history section.
4. Grep the skill library for the ID (`grep -rn "E<n>" .claude/skills/`) and flip any skill that referenced it to past tense.

### Table history

| Date | Change |
|---|---|
| 2026-07-02 | Table created from the doc-drift audit at commit `4439c17` (v1.5.2 + 1 docs commit). 45 rows, all open. Phase-4 doc-fix pass planned. |
| 2026-07-02 | **Phase-4 doc-fix pass executed**: all 45 rows (E1-E45) fixed in the docs of record and verified; rows moved to the resolved list. Open count: **0**. `CLAUDE.md` rewritten as the router (task→skill table) and now codifies the skills-English carve-out and the skill-provenance maintenance rule. |

## Provenance and maintenance

Run from repo root. If any check fails, update the corresponding section of this skill in the same PR.

- Doc inventory still matches the doc map: `ls .claude/*.md` (expect the 11 docs listed in the map, plus `skills/`).
- Language policy source lines: `sed -n 35,39p .claude/rules.md` (Spanish internal/commits, English README+CHANGELOG+code).
- Skills-in-English carve-out codified in `CLAUDE.md` (2026-07-02): `grep -n "skills" CLAUDE.md` — expect hits (the "Idioma" rule bullet and the skills documentation layer/routing sections). If it ever returns nothing, `CLAUDE.md` regressed: this skill's language table becomes the fallback authority again — flag it.
- Commit style: `sed -n 9p .claude/rules.md`. Release-commit shape: `grep -n "chore(release)" .claude/versioning.md`.
- CHANGELOG format declaration: `sed -n 1,7p CHANGELOG.md` (Keep a Changelog 1.1.0 + SemVer, `[Unreleased]` present). Move-at-release rule: `grep -n "Unreleased" .claude/versioning.md`.
- README voice anchor (v1.5.2 end-user rewrite): `grep -n "README rewritten" CHANGELOG.md`. Commit sha `9ca0f8a` — verified: `git show -s 9ca0f8a` ("docs(readme): reescritura end-user…", 2026-06-11).
- Errata: the open table is expected EMPTY (as of 2026-07-02) — any new row must carry its own re-verify command. The resolved list is frozen history (do not re-verify resolved rows; the original rows with full code-truth columns and commands live in git history at the pre-fix revision of this file). Spot-check anchors last re-verified 2026-07-02: `ci.yml:35,38,44`, `routes/api/radarr.py:39,54,81`, `alembic/versions/0002_settings_per_entity.py:25`, `config.py:42,46,47`, `Dockerfile:23-24`.
- Current version for date-stamps: `grep -n "^version" pyproject.toml` (1.5.2 as of 2026-07).
- Skill-name cross-references still valid: `ls .claude/skills/` and compare against the names used in the doc-update triggers table.
