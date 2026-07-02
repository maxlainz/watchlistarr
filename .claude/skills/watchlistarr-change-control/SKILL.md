---
name: watchlistarr-change-control
description: Change-control discipline for the watchlistarr repo — consult BEFORE any commit, push, merge, version bump, release cut, migration edit, or change to the Radarr-facing surface. Covers the branch model (work on dev, never commit to main, merge only on explicit request with a "Merge dev: <resumen>" summary message), Spanish commit messages, commit+push after every edit, the 5-step pre-push CI gate, the "Radarr payload is sacred" enforcement checklist (schemas/radarr.py, services/radarr.py, routes/api/radarr.py), what counts as a BREAKING change, the release procedure (double bump, uv lock before commit, annotated tags from main only), Alembic migration rules, and the ci.yml self-change protocol. NOT for running/debugging the CI steps or the test-suite map → use `watchlistarr-validation-and-qa`; NOT for Radarr contract internals or StevenLuParser behavior → use `radarr-integration-reference`; NOT for full incident histories → use `watchlistarr-failure-archaeology`; NOT for docker compose / QC-loop mechanics → use `watchlistarr-run-and-operate`; NOT for doc-language policy or the errata table → use `watchlistarr-docs-and-writing`.
---

# watchlistarr change control

Every change to this repo flows through the same pipeline: edit → local 5-step gate → commit on `dev`
(Spanish message) → push → dev-container rebuild → (on explicit request) merge to `main` → (optionally)
release tag from `main`. This skill defines each gate and the special rules for the two most dangerous
change categories: the Radarr-facing surface and Alembic migrations.

## When to use

- You are about to commit, push, or you were asked to "merge to main" or "cut a release".
- Your diff touches `src/watchlistarr/schemas/radarr.py`, `src/watchlistarr/services/radarr.py`, or
  `src/watchlistarr/routes/api/radarr.py` and you need to know what that obligates you to do.
- You changed anything under `src/watchlistarr/models/` and need the migration rules.
- You need to decide whether a change is MAJOR / MINOR / PATCH, or whether to release at all.
- You edited `.github/workflows/ci.yml` and want to know how to validate it.
- You added/removed an HTTP route, changed a JSON shape, or renamed a model, and need to know which
  test/smoke files must change in the same commit.

## When NOT to use

| Need | Use instead |
|---|---|
| How to run the 5 CI steps, what each covers, test-suite map, smoke.py anatomy | `watchlistarr-validation-and-qa` |
| What the Radarr JSON contract means, parser behavior, mass-delete risk | `radarr-integration-reference` |
| Full story of a past incident (v1.2.2 retag, enum bug, cooldown revert…) | `watchlistarr-failure-archaeology` |
| Rebuilding/running the dev container, QC on the local instance, admin endpoints | `watchlistarr-run-and-operate` |
| uv/lockfile mechanics, Docker image anatomy | `watchlistarr-build-and-env` |
| Doc house style, language policy, the standing errata table | `watchlistarr-docs-and-writing` |

## Branch model (as practiced)

Ground truth: `.claude/rules.md:5-9` plus the repo's actual git history.

1. **All work happens on `dev`.** Never commit directly to `main` (`rules.md:5`).
2. **Merge `dev` → `main` ONLY when the user explicitly asks.** No exceptions — not for "it's just
   docs", not for hotfixes, not because CI is green (`rules.md:7`).
3. **Merge commit message format** (stable practice since v1.2.0; fullest example: merge commit
   `5416a65`):
   - Subject: `Merge dev: <resumen>` — Spanish, one line.
   - Body: enumerates **everything** new since the previous commit on `main`, not just the latest
     change. Build it from `git log --oneline main..dev` before merging.
4. **`CLAUDE.md` and `.claude/` DO travel to `main`** — never exclude them in the merge, unlike other
   personal projects (`rules.md:8`, `CLAUDE.md`).
5. Tags are cut **only from `main`**, never from `dev` (`versioning.md:33`). See the release section.

```bash
# The merge itself (only on explicit request):
git checkout main
git merge dev          # write the "Merge dev: <resumen>" message with enumerated body
git push origin main
```

## Commit discipline

- **Language: Spanish.** Short, descriptive messages. Conventional prefixes (`feat:`, `fix:`,
  `docs:`, `chore:`, `refactor:`, `ci:`, `test:`) are welcome but not mandatory (`rules.md:9`) —
  they do feed the release-bump decision table, so prefer them.
- **Commit + push after every code edit**, then rebuild the local dev container for manual QC
  (`rules.md:6`, `CLAUDE.md`). Rebuild command and the QC-port caveat (the `:8088` port comes from
  the owner's uncommitted `.env`; compose defaults to 8080) live in `watchlistarr-run-and-operate`.
- The only fixed message format in the repo is the release commit: `chore(release): vX.Y.Z`.
- Skills/docs are in English, but commit messages stay Spanish even for English-content commits.

## Pre-push gate: the 5 CI steps

Never push without running the full local gate. The 5 CI steps (`.github/workflows/ci.yml`):
`uv sync --frozen` then `uv run ruff check src tests` · `uv run ruff format --check src tests` ·
`uv run mypy src` · `uv run pytest --cov=src/watchlistarr --cov-report=term` ·
`uv run python scripts/smoke.py`. House rule adds `scripts` to both ruff invocations locally
(CI does not lint scripts — asymmetry is a known erratum).

Single local block (from `rules.md:21-29`):

```bash
uv run ruff check src tests scripts && \
uv run ruff format --check src tests scripts && \
uv run mypy src && \
uv run pytest -q && \
uv run python scripts/smoke.py
```

A failure in any step blocks the push. Step-by-step anatomy, what each catches, and known
local/CI asymmetries: `watchlistarr-validation-and-qa`.

Same-commit coupling rules (`rules.md:15-18`):

| If your diff… | …the same commit must also contain |
|---|---|
| Adds unformatted code | Output of `uv run ruff format src tests scripts` (the `--check` step breaks silently otherwise) |
| Renames a model, changes DB schema, alters an HTTP route, or changes a JSON shape | Updated `scripts/smoke.py` (the only end-to-end safety net in CI) |
| Adds/removes deps in `pyproject.toml` | Refreshed `uv.lock` via `uv lock` (CI runs `uv sync --frozen` and fails on mismatch) |
| Adds/deletes HTTP routes | Updated 404 asserts in `scripts/smoke.py` AND `tests/integration/test_ui_smoke.py` so dead routes stay verified dead |
| Changes anything under `src/watchlistarr/models/` | An Alembic revision (see migration section) |

## The unwritten law, now written: the Radarr payload is sacred

Radarr polls three root-level unauthenticated GET routes and auto-adds (and can mass-delete) movies
based on what they serve. Any silent change here breaks every downstream Radarr instance at its next
poll. The served item is, canonically: array of
`{"id": <tmdb_id>, "tmdb_id": <tmdb_id>, "title": "<str>", "imdb_id": "tt…"}`, `imdb_id` key omitted
(not null) when unknown; media type `application/json; charset=utf-8`; weak ETag `W/"sha1"`;
If-None-Match hit → 304. (`schemas/radarr.py`, `services/radarr.py`, `routes/api/radarr.py:26-36`).
Full contract semantics and why omission matters: `radarr-integration-reference`.

### What counts as "touching the payload"

Any diff in these files/behaviors, however small:

| Surface | File | Sacred aspects |
|---|---|---|
| Item schema | `src/watchlistarr/schemas/radarr.py` | `RadarrItem` fields (`id`, `tmdb_id`, `title`, `imdb_id`), types, optionality (`schemas/radarr.py:6-13`) |
| Serialization | `src/watchlistarr/services/radarr.py` | `exclude_none` omission of `imdb_id`, compact separators, `id == tmdb_id`, item selection/ordering in `serialize_list`/`serialize_custom_list` (changed bytes ⇒ changed ETag ⇒ Radarr re-syncs), `compute_etag` format (`services/radarr.py:17-65`) |
| Routes | `src/watchlistarr/routes/api/radarr.py` | URL scheme incl. trailing slashes (`/lists/{slug}/`, `/{username}/watchlist/`, `/{username}/{slug}/` at `radarr.py:39,54,81`), 404 semantics (unknown user/slug, `enabled=False` lists, `RESERVED_USERNAMES` at `radarr.py:60,88`), 304/ETag handling and media type (`radarr.py:26-36`) |

### What touching it requires — the enforcement checklist

Do ALL of these; skipping any one is a rule violation:

1. **Treat it as a BREAKING change → MAJOR bump** per `.claude/versioning.md` (MAJOR = incompatible
   change to a stable surface, and the Radarr endpoint + JSON shape are the first-listed stable
   surface, `versioning.md:9-12`).
2. **Update `scripts/smoke.py` asserts in the SAME commit.** The Radarr asserts live at
   `scripts/smoke.py:314-382`: item shape and `id == tmdb_id` (L318-332), `imdb_id` omission for a
   film without one (L326), 404 for unknown user and for disabled list (L366-371), ETag/304
   round-trip (L374-377).
3. **Update `tests/integration/test_radarr_routing.py`** — the integration suite that pins routing,
   404, and serialization behavior.
4. **Get explicit user sign-off BEFORE merging to `main`.** State plainly in your report: "this
   changes the payload Radarr consumes; existing Radarr list URLs / imports will be affected"; do
   not merge until the user acknowledges.

Refactors that provably keep the served bytes identical (e.g. moving a helper) are not breaking,
but steps 2–3 still apply as verification: the asserts must still pass unchanged.

## What makes a change BREAKING here

Per `.claude/versioning.md:9-16` — with one correction:

> **Erratum**: `versioning.md:10` currently claims the Radarr endpoint is `/radarr/list/{id}` — wrong
> as of 2026-07 (so is `workflows.md:43`'s `/list/<list_id>`); see the standing errata table in
> `watchlistarr-docs-and-writing`. The real stable surfaces are `/lists/{slug}/`,
> `/{username}/watchlist/`, `/{username}/{slug}/` (`routes/api/radarr.py:39,54,81`), mounted at app
> root (`main.py:103`).

**MAJOR** (breaking):
- Any incompatible change to the Radarr surface: URL scheme, JSON shape, `imdb_id` omission
  behavior, 404 semantics, ETag/304 behavior (previous section).
- Required env vars renamed or removed.
- DB schema change **without** an automatic Alembic migration.

**MINOR**: new backwards-compatible functionality — new endpoints, new optional env vars, new
scrapers, DB changes WITH their migration.

**PATCH**: backwards-compatible bugfix; no schema or contract changes.

**No release at all**: only `docs:`/`chore:`/`refactor:`/`ci:`/`test:` commits since the last tag
(`versioning.md:27`).

The `0.x.y` carve-out ("breaking allowed in MINOR") in `versioning.md:7` is inactive — the project
is at 1.5.2 (as of 2026-07): `grep -n '^version' pyproject.toml`.

## Release procedure (summary — full detail in `.claude/versioning.md:49-64`)

Prerequisites: on `main`, up to date, remote CI green, `dev` already merged (on explicit request).

1. Decide the bump from the conventional-commits table above → compute `X.Y.Z`.
2. **Double bump, mandatory**: `version = "X.Y.Z"` in `pyproject.toml` AND `__version__ = "X.Y.Z"`
   in `src/watchlistarr/__init__.py` — bumping only one desyncs `/healthz` from the package.
3. `CHANGELOG.md`: move `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`, create a fresh empty
   `[Unreleased]` above. **Entries in English** (public-facing file).
4. **`uv lock` BEFORE the commit** — the lockfile embeds the package's own version and CI's
   `uv sync --frozen` fails on mismatch. Verify:
   `grep -A1 'name = "watchlistarr"' uv.lock | grep version`.
5. Run the full local 5-step gate.
6. Commit exactly 4 files (`pyproject.toml`, `src/watchlistarr/__init__.py`, `CHANGELOG.md`,
   `uv.lock`) as `chore(release): vX.Y.Z`.
7. **Annotated tag, from `main` only**: `git tag -a vX.Y.Z -m "vX.Y.Z"` — never lightweight, never
   from `dev` (`versioning.md:31-33`).
8. `git push origin main && git push origin vX.Y.Z`. The tag push triggers the multi-arch Docker
   build publishing `X.Y.Z` and `X.Y` to Docker Hub + GHCR (`ci.yml:49-101`). Post-push
   verification steps: `versioning.md:66-77`.

> Historical pitfall (v1.2.2): step 4 was skipped, so the release commit carried a stale `uv.lock`
> and fixing it required amend + delete remote tag + retag + force-push of `main`. Full story:
> `watchlistarr-failure-archaeology`.

## Migration change-control

Every boot runs `alembic upgrade head` (`src/watchlistarr/main.py:40-42`), and `scripts/smoke.py`
upgrades a fresh DB from zero (`smoke.py:398-401`) — so the migration chain is exercised on every
push, but only against SQLite.

- **Any change under `src/watchlistarr/models/` → an autogenerated Alembic revision in the SAME
  commit** (`workflows.md:24-27`). House convention is sequential zero-padded revision ids
  (`alembic/versions/0001_…` through `0009_…` as of 2026-07); match it with `--rev-id`:

  ```bash
  uv run alembic revision --autogenerate --rev-id 0010 -m "describe change"
  uv run alembic upgrade head
  ```

- **Review the autogenerated diff before committing** — mypy excludes `alembic/versions`
  (`pyproject.toml:69`), so nothing checks migrations but your eyes and the smoke run.
- **Never edit an already-applied (pushed) migration.** Existing DBs recorded it in
  `alembic_version` and will never re-run it; edits silently fork fresh installs from upgraded
  ones. Fix mistakes with a new forward revision.
- **SQLite masks enum/DDL strictness bugs**: migration 0003 shipped with a value missing from an
  enum and SQLite's loose typing hid it until `d8ae10c` / migration 0006 (v1.2.3). Full story and
  the generalized lesson: `watchlistarr-failure-archaeology` (incident: latent Postgres enum bug).

## When `ci.yml` itself changes

The 5 local steps validate your code, **not the workflow file** — there is no local validation for
`.github/workflows/ci.yml` (`rules.md:19`). Protocol:

1. Before changing an action pin, verify the ref actually exists:
   `git ls-remote --tags https://github.com/<owner>/<action>`. Not every action publishes floating
   major tags — e.g. `astral-sh/setup-uv` only publishes floating minors like `v8.2`
   (`ci.yml:24` pins `astral-sh/setup-uv@v8.2.0`).
2. Push to `dev`, then **wait for the remote run to go green before merging to `main`**:
   `gh run list --branch dev --limit 1`, then `gh run watch`.
3. Know the coverage gap: pushes to `dev` exercise only the `qa` job — the `docker` job runs only on
   `main` and `v*` tags (`ci.yml:53`), so edits to the docker job are first exercised by the merge
   or the release tag itself. Flag this to the user when touching that job.

## Checklists

### Before you push (every commit on `dev`)

| # | Check | How |
|---|---|---|
| 1 | Code formatted | `uv run ruff format src tests scripts` |
| 2 | Full 5-step gate green | Single block from the pre-push section |
| 3 | Models touched? | Alembic revision with sequential `--rev-id` in this commit |
| 4 | `pyproject.toml` deps touched? | `uv lock` ran; `uv.lock` staged |
| 5 | Routes / JSON shapes / model names touched? | `scripts/smoke.py` updated; route deletions also update 404 asserts in `smoke.py` + `tests/integration/test_ui_smoke.py` |
| 6 | Radarr surface touched? | Full sacred-payload checklist above (MAJOR + smoke + `test_radarr_routing.py` + planned user sign-off) |
| 7 | Commit message | Spanish, short, conventional prefix if it fits |
| 8 | After push | Rebuild dev container for QC — `watchlistarr-run-and-operate` |

### Before you merge to `main`

| # | Check | How |
|---|---|---|
| 1 | User explicitly requested the merge | If not: stop |
| 2 | Remote CI green on `dev` | `gh run list --branch dev --limit 1` |
| 3 | `ci.yml` changed since last merge? | Green **remote** run is mandatory, not just local gate |
| 4 | Radarr surface changed? | User sign-off recorded; MAJOR release planned |
| 5 | Merge message | Subject `Merge dev: <resumen>`; body enumerates ALL of `git log --oneline main..dev` |
| 6 | `CLAUDE.md` / `.claude/` | Included in the merge — never excluded in this repo |
| 7 | Major architecture/command/rule changes in this batch? | Corresponding `.claude/` docs updated — `watchlistarr-docs-and-writing` |
| 8 | Release next? | Follow the release procedure; tag only from `main`, annotated |

## Provenance and maintenance

Facts here drift with the repo. Re-verify before trusting (all from repo root):

| Fact | Re-verify with |
|---|---|
| Branch/commit/merge rules | `sed -n '3,9p' .claude/rules.md` |
| Merge-message practice (`Merge dev: <resumen>`) | `git log --merges --pretty='%h %s' main \| head` |
| The 5 CI steps and their exact commands | `grep -n 'run: uv' .github/workflows/ci.yml` |
| CI lints `src tests` only (scripts asymmetry) | `grep -n 'ruff' .github/workflows/ci.yml` |
| Radarr routes + trailing slashes | `grep -n '@router.get' src/watchlistarr/routes/api/radarr.py` |
| RadarrItem fields | `cat src/watchlistarr/schemas/radarr.py` |
| Payload bytes semantics (`exclude_none`, ETag) | `grep -n 'exclude_none\|sha1' src/watchlistarr/services/radarr.py` |
| Radarr router mounted at root | `grep -n 'include_router' src/watchlistarr/main.py` |
| smoke.py Radarr assert block | `grep -n 'watchlist/\|/lists/\|If-None-Match' scripts/smoke.py` |
| Radarr integration test exists | `ls tests/integration/test_radarr_routing.py` |
| SemVer table + release steps + v1.2.2 pitfall | `cat .claude/versioning.md` |
| versioning.md URL erratum still unfixed? | `grep -n 'radarr/list' .claude/versioning.md` (hit ⇒ erratum stands) |
| Double-bump pair in sync | `grep -n '^version' pyproject.toml && cat src/watchlistarr/__init__.py` |
| Current migration head / next `--rev-id` | `ls alembic/versions/ \| sort \| tail -1` |
| Boot-time `upgrade head` | `grep -n 'command.upgrade' src/watchlistarr/main.py` |
| mypy excludes migrations | `grep -n 'exclude' pyproject.toml` |
| ci.yml self-change rule (`rules.md` L19) | `sed -n '19p' .claude/rules.md` |
| docker job trigger condition | `grep -n "if: github.event_name" .github/workflows/ci.yml` |
| Current version (dates any stated number) | `grep -n '^version' pyproject.toml` |

Line anchors cited in this skill were verified 2026-07 at v1.5.2 (HEAD one docs commit past the
tag). If an anchor misses, re-run the matching command above rather than trusting the number.
