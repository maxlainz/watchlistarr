---
name: radarr-integration-reference
description: Everything Radarr for watchlistarr — the exact served URL surface (/lists/{slug}/, /{username}/watchlist/, /{username}/{slug}/), the canonical JSON item contract (id/tmdb_id/title/imdb_id, exclude_none, weak SHA-1 ETag, 304), how Radarr's two parsers (Custom Lists, StevenLu Custom) read the payload, why films without imdb_id are invisible to StevenLu, raw-vs-custom serve-time semantics (snapshot mode, RATING_DESC re-sort, max_items), the mass-delete risk, Radarr-side setup, and a failure-mode table. Use when Radarr says "No results were returned from your import list", Test fails, imports nothing, library items vanish, or you are changing anything under routes/api/radarr.py, schemas/radarr.py, services/radarr.py. NOT for Letterboxd scraping/selectors → use `letterboxd-scraping-reference`; NOT for anti-flap internals or system invariants → use `watchlistarr-architecture-contract`; NOT for step-by-step live debugging trees → use `watchlistarr-debugging-playbook`; NOT for release/breaking-change gates → use `watchlistarr-change-control`.
---

# Radarr integration reference

watchlistarr never calls Radarr's API. The integration is one-way: Radarr polls three
unauthenticated GET endpoints on watchlistarr and parses the JSON array they return. Everything
served is a SELECT from the SQLite DB — never a live scrape (DB-authoritative principle, see
`watchlistarr-architecture-contract`).

## When to use

- Radarr shows "No results were returned from your import list", Test fails, or a list imports nothing.
- Movies are disappearing from the Radarr library or the served list "flickers" between polls.
- You are about to edit `src/watchlistarr/routes/api/radarr.py`, `src/watchlistarr/schemas/radarr.py`, or `src/watchlistarr/services/radarr.py`.
- You need the exact URL to paste into Radarr, or to explain why a film in the DB never gets imported.
- You need to know what counts as a breaking change to the Radarr surface.

## When NOT to use

- Letterboxd URLs, selectors, RSS, rate limits, 403s → `letterboxd-scraping-reference`.
- Why an item was (not) removed from `list_items` (anti-flap mechanics) → `watchlistarr-architecture-contract`.
- Full symptom→fix decision trees for a live incident → `watchlistarr-debugging-playbook`.
- Enforcing the breaking-change/release process → `watchlistarr-change-control`.
- Full historical incident stories → `watchlistarr-failure-archaeology`.

## The law: the Radarr payload is sacred

Never change the served JSON shape, the URL scheme, or the 404 semantics without treating it as a
breaking change (major version bump) AND updating the `scripts/smoke.py` Radarr asserts
(`scripts/smoke.py:314-377`) in the same commit. The enforcement checklist (what exactly triggers
a major bump, gates before push/merge) lives in `watchlistarr-change-control` — this skill only
defines what the contract IS.

## Served URL surface (exact paths — trailing slashes matter)

Three root-level, unauthenticated GET routes, all in `src/watchlistarr/routes/api/radarr.py`
(as of 2026-07, v1.5.2):

| Route (exact) | Serves | 404 when | Anchor |
|---|---|---|---|
| `GET /lists/{slug}/` | Custom list (multi-source, materialized) | slug unknown (`"custom list does not exist"`) | `radarr.py:39-51` |
| `GET /{username}/watchlist/` | User's raw watchlist | username reserved; user unknown (`"user not found"`); watchlist row missing or `lists.enabled=False` (`"watchlist not found"`) | `radarr.py:54-78` |
| `GET /{username}/{slug}/` | User's raw Letterboxd list | username reserved; user unknown; list unknown or `lists.enabled=False` (`"slug not found for user"`) | `radarr.py:81-103` |

Rules and pitfalls:

- **Paths are declared WITH trailing slash.** Configure Radarr with the trailing slash. `main.py:75`
  does not override FastAPI's default slash-redirect behavior, so a slashless request gets a
  redirect rather than the payload directly — whether Radarr follows it is untested here; do not
  rely on it.
- **`/list/<list_id>` and `/radarr/list/{id}` DO NOT EXIST** — and never did. `workflows.md` and
  `versioning.md` previously claimed them (fixed 2026-07-02; E25/E36 in
  `watchlistarr-docs-and-writing`) — both docs now list the three real routes. Old Radarr configs
  or notes may still carry the fictional URLs.
- **RESERVED_USERNAMES guard**: the two `{username}` routes return a bare 404 when
  `username in RESERVED_USERNAMES` — the frozenset `{"all", "api", "admin", "static", "health",
  "_", "lists"}` (`src/watchlistarr/services/scrape/initial_run.py:15-17`, checked at
  `radarr.py:60,88`). Routers are registered admin → api/v1 → radarr (`main.py:101-103`), so
  `/api/...`, `/admin/...`, `/healthz`, `/static/...` match their own routes before the
  `/{username}/{slug}/` catch-all; the guard is the belt-and-suspenders on top.
- **Asymmetry**: raw lists 404 when `lists.enabled=False`; the custom-list route NEVER checks
  `custom_lists.enabled` (dead flag, default True, no endpoint toggles it — `radarr.py:39-51`).
  A "disabled" custom list still serves. Treat fixing this as open candidate work, not current behavior.
- Old combined routes (`/all/watchlist/union/` etc.) are gone — 404
  (`tests/integration/test_radarr_routing.py:281-290`).
- No auth on any of the three routes: anyone who can reach the port can read every list.

## The canonical Radarr item

State this exactly (canonical formula, do not paraphrase):

**Radarr item**: array of `{"id": <tmdb_id>, "tmdb_id": <tmdb_id>, "title": "<str>", "imdb_id": "tt…"}`,
`imdb_id` key omitted (not null) when unknown; media type `application/json; charset=utf-8`;
weak ETag `W/"sha1"`; If-None-Match hit → 304. (`schemas/radarr.py`, `services/radarr.py`,
`routes/api/radarr.py:26-36`)

Why it looks like this:

- **`id == tmdb_id` always** (`services/radarr.py:27,54`; smoke asserts it at
  `scripts/smoke.py:321,332`). Radarr's "Custom Lists" provider reads the `id` field and treats it
  as a TMDB id; `tmdb_id` is an alias kept for debugging and our own tooling. Serving both makes one
  payload work for both Radarr providers (Newtonsoft deserializes each provider's DTO and silently
  ignores unknown fields).
- **`imdb_id` is OMITTED, never `null`**, when `films.imdb_id` is NULL. Same for `title`.
  Mechanism: `RadarrItem` fields default to `None` (`schemas/radarr.py:11-12`) and
  `render_payload` dumps with `model_dump(exclude_none=True)` (`services/radarr.py:60`).
  Tests pin this (`test_radarr_routing.py:223-224`, `smoke.py:326`).
- **Root-level JSON array** — never wrap in an object. A wrapped array parses as empty in Radarr
  with no visible error (`.claude/radarr-custom-list.md` L130, Radarr/Radarr#9139).
- **`id`/`tmdb_id` must be JSON integers**, not strings (smoke asserts `isinstance(..., int)`).
- Serialization details (`services/radarr.py:59-65`): compact separators `(",", ":")`,
  `ensure_ascii=False`, UTF-8 bytes; `RadarrItem` has `extra="forbid"` so accidental extra fields
  fail loudly at construction time.
- **ETag / 304**: `compute_etag` returns `W/"<sha1-hex-of-payload-bytes>"`; the route compares the
  raw `If-None-Match` header by exact string equality and returns 304 with the ETag header on a hit
  (`routes/api/radarr.py:26-36`). This is IMPLEMENTED and smoke-tested (`smoke.py:374-377`);
  `radarr-custom-list.md` L137-139 now documents it as implemented (it previously called it
  future work — fixed 2026-07-02; E35). Note Radarr itself does not currently send `If-None-Match`
  (community observation recorded in `radarr-custom-list.md` L138, unverified against current Radarr).

## How Radarr parses the payload (two providers, one URL)

Radarr has two URL-based import-list providers; both work against the same watchlistarr URL.
Source: `.claude/radarr-custom-list.md` (reverse-engineered from Radarr source; there is no
official spec — Radarr/Radarr#8370 was closed *not planned*).

| Provider (Radarr UI) | Reads | Ignores | Item discarded when |
|---|---|---|---|
| **Custom Lists** (`RadarrListParser.cs`) | `id` → TmdbId | `title`, `imdb_id`, `tmdb_id` | `id` missing or ≤ 0 |
| **StevenLu Custom** (`StevenLuParser.cs`) | `title` + `imdb_id` | `id`, `tmdb_id` | `imdb_id` missing → **silently dropped** |

**The invisible-film problem (StevenLu side)**: because `imdb_id` is omitted when
`films.imdb_id` is NULL, a film watchlistarr serves perfectly well is INVISIBLE to a
"StevenLu Custom" list in Radarr. A payload where every item lacks `imdb_id` produces Radarr's
"No results were returned from your import list". This was live incident territory: `films.imdb_id`
+ migration 0004 + backfill were added for exactly this (`59ad738`, v1.0.1) — full story in
`watchlistarr-failure-archaeology`.

Check imdb_id coverage of everything currently served — this UNION query is the reference form
of the imdb-coverage check; siblings keep short variants and link here. (Run from repo root; dev
default DB is `data/watchlistarr.db` per `config.py:45`; in Docker the same file is
`/data/watchlistarr.db` inside the container = `./data/watchlistarr.db` on the host,
`docker-compose.dev.yml:10`):

```bash
sqlite3 data/watchlistarr.db "
SELECT 'raw:'||u.letterboxd_username||'/'||l.slug AS endpoint,
       SUM(f.imdb_id IS NULL) AS invisible_to_stevenlu, COUNT(*) AS served
FROM list_items li JOIN films f USING (tmdb_id)
JOIN lists l ON l.id = li.list_id JOIN users u ON u.id = l.user_id
WHERE l.enabled = 1 GROUP BY l.id
UNION ALL
SELECT 'custom:'||cl.slug, SUM(f.imdb_id IS NULL), COUNT(*)
FROM custom_list_items cli JOIN films f USING (tmdb_id)
JOIN custom_lists cl ON cl.id = cli.custom_list_id GROUP BY cl.id;"
```

`invisible_to_stevenlu > 0` on a StevenLu-configured list = films that will never import there.
Prefer the **Custom Lists** provider (resolves by TMDB id, does not depend on scraped imdb_id);
where the imdb_id comes from is `letterboxd-scraping-reference` territory.

## Raw lists vs custom lists at serve time

| Aspect | Raw (`/{user}/watchlist/`, `/{user}/{slug}/`) | Custom (`/lists/{slug}/`) |
|---|---|---|
| Source table | `list_items` | `custom_list_items` (materialized by editor save / rotation / snapshot refresh) |
| Filters at serve | **None** — unfiltered | None at serve; year/watched-exclusion/`added_after`-`added_before` filters run at materialization time, not per GET |
| Cap at serve | **None** — uncapped | `max_items` applied as SQL `LIMIT` (`services/radarr.py:50-51`) |
| Order at serve | `position, tmdb_id` (`services/radarr.py:17-29`) | See ordering rules below |
| Disabled → 404 | Yes (`lists.enabled`) | No (`custom_lists.enabled` never checked) |

Custom-list ordering rules at serve (`serialize_custom_list`, `services/radarr.py:32-56`):

1. **Snapshot mode** (`custom_lists.snapshot_interval IS NOT NULL`): always serve persisted
   `position, tmdb_id` order — the output stays frozen between snapshot refreshes regardless of
   `sort_order`.
2. **Non-snapshot + `sort_order = RATING_DESC`**: re-sort at serve time by
   `letterboxd_avg_rating DESC` (NULL ratings last, `position` as tiebreak) — the ONLY sort applied
   per-GET. Rating drift between polls therefore reorders the payload, and with `max_items` it can
   rotate films in/out of the served window. Snapshot mode exists precisely to stop that churn (it
   replaced the reverted scrape-cooldown, `c8991da` — full story in `watchlistarr-failure-archaeology`).
3. **Everything else** (`LETTERBOXD`, `REVERSE`, `RANDOM`, enum at `models/enums.py:47-51`): serve
   persisted `position, tmdb_id` — those sorts are baked into positions at materialization.

Raw lists get NO serve-time policy at all. (`radarr-custom-list.md` §"Políticas al servir: raw vs
custom" now states this correctly; its old "Filtros aplicados antes de servir" section described
pre-multi-source serve-time sort/max/watched-exclusion on a fictional `GET /list/<list_id>` —
fixed 2026-07-02; E34.)

## The mass-delete risk (why this project exists)

Depending on the user's list-removal settings in Radarr (the clean-library / list-sync options —
exact option names unverified here), Radarr will unmonitor or DELETE library movies that vanish
from a synced import list. Consequences for watchlistarr:

- **Serving `[]` or a partial list because of a bug is catastrophic** — it can wipe a library.
  `[]` is only legitimate for a genuinely empty list (fresh instance; Radarr's Test accepts it).
- **Fail loudly, never partially.** The routes either serve the full SELECT or raise; unhandled
  exceptions become a 500 (`main.py:89-99`). Radarr treats 404/5xx as "list in error state, keep
  last known items, retry next sync" (`radarr-custom-list.md` L133) — an error response is SAFE,
  a wrong 200 is not.
- Item removals from the DB itself must pass the anti-flap confirmation rule, and scrapes are
  transactional with no HTTP inside write transactions, so a mid-scrape crash can't leave a
  half-empty list to serve. Those invariants and the canonical anti-flap formula live in
  `watchlistarr-architecture-contract`.

## Configuring Radarr (Radarr side)

1. In Radarr: **Settings → Import Lists → ➕** → choose **Custom Lists** (recommended: resolves by
   TMDB id) or **StevenLu Custom** (requires imdb_id coverage, see above).
2. **List URL** — exact, WITH trailing slash:
   - `http://<host>:<port>/lists/<slug>/` for a custom list,
   - `http://<host>:<port>/<username>/watchlist/` for a user watchlist,
   - `http://<host>:<port>/<username>/<slug>/` for a raw user list (must be enabled).
   Same Docker network → use the service name as host. Container listens on 8080; `HTTP_PORT` only
   moves the host-side compose mapping (`docker-compose.dev.yml:8`).
3. Enable Automatic Add, Monitor, Quality Profile, Root Folder, Minimum Availability: user's choice.
4. **Test** → Radarr fetches the URL once and parses it; any 200 with a parseable root array passes,
   including `[]`. Test passing does NOT prove items will import (StevenLu + no imdb_ids passes
   Test, then imports nothing).
5. **Save.** Polling cadence is owned entirely by Radarr (historic default 6 h, minimum accepted
   ~1 h — community-sourced, `radarr-custom-list.md` L26). watchlistarr cannot influence it; every
   GET is a cheap DB read, so cadence does not matter to us.
6. N lists in Radarr can point at the same watchlistarr host; the path distinguishes them.

## Failure modes: symptom in Radarr → cause → where to look

Full step-by-step trees live in `watchlistarr-debugging-playbook`; this is the map.

| Symptom in Radarr | Likely cause | Where to look |
|---|---|---|
| "No results were returned from your import list" (StevenLu provider) | Served items lack `imdb_id`, or list is genuinely empty | Coverage SQL above; `curl <url> \| python3 -m json.tool`; `films.imdb_id` backfill (`watchlistarr-failure-archaeology`, `59ad738`) |
| Test fails | Wrong URL (missing trailing slash, `/list/<id>` fiction, reserved username), 404 (user/list unknown or `lists.enabled=False`), watchlistarr down/unreachable | `curl -i` the exact URL; 404 detail string tells you which branch fired (`radarr.py:49,61,66,76,89,94,101`) |
| Test OK but nothing imports (Custom Lists provider) | `id` missing/0/string, or payload wrapped in an object (both impossible via `render_payload` — suspect a proxy or a local code change) | `services/radarr.py:59-61`; smoke asserts (`smoke.py:319-321`) |
| Nothing imports, no error | "Enable Automatic Add" off in Radarr; TMDB id nonexistent (Radarr logs "movie not found" and skips) | Radarr's own settings and logs |
| Library movies disappearing | The served list actually shrank: item removals (anti-flap should gate these), a `max_items` window rotating under RATING_DESC re-sort, or rotation/materialization changes to `custom_list_items` | `watchlistarr-debugging-playbook`; anti-flap state in `list_items.pending_removal_count`; consider snapshot mode |
| List content flaps between polls (add/remove churn) | Non-snapshot `RATING_DESC` + `max_items`: rating drift reorders the cap window at serve time | `services/radarr.py:41-51`; set `snapshot_interval`; cautionary tale in `watchlistarr-failure-archaeology` (cooldown revert) |
| Radarr shows list in error state | watchlistarr returned 404/5xx; Radarr keeps last state and retries — safe by design | App logs (`request.unhandled_exception`), `/healthz` |

## Provenance and maintenance

Verified against code at v1.5.2 (2026-07). Re-verify each fact block before trusting it after
edits to the Radarr surface:

| Fact | Re-verify command (from repo root) |
|---|---|
| Route paths + 404 branches | `grep -n "@router.get\|HTTPException" src/watchlistarr/routes/api/radarr.py` |
| RESERVED_USERNAMES set | `grep -n -A2 "RESERVED_USERNAMES" src/watchlistarr/services/scrape/initial_run.py` |
| Item schema (fields, extra=forbid) | `cat src/watchlistarr/schemas/radarr.py` |
| exclude_none / compact JSON / ETag | `grep -n "exclude_none\|separators\|sha1" src/watchlistarr/services/radarr.py` |
| 304 handling + media type | `sed -n 26,36p src/watchlistarr/routes/api/radarr.py` |
| Raw serve = unfiltered/uncapped/position | `sed -n 17,29p src/watchlistarr/services/radarr.py` |
| Custom serve ordering + snapshot + LIMIT | `sed -n 32,56p src/watchlistarr/services/radarr.py` |
| custom_lists.enabled never checked | `grep -n "enabled" src/watchlistarr/routes/api/radarr.py` — expect exactly two hits (:75, :100 — the raw routes); no hit inside `custom_list_endpoint` (:39-51) confirms the claim |
| SortOrder members | `sed -n 47,51p src/watchlistarr/models/enums.py` |
| Router registration order | `grep -n "include_router" src/watchlistarr/main.py` |
| Smoke asserts (the contract's safety net) | `sed -n 314,377p scripts/smoke.py` |
| Integration tests for routing/ETag | `grep -n "^def test_" tests/integration/test_radarr_routing.py` |
| Radarr parser behavior (external) | `.claude/radarr-custom-list.md` L7-121 + the linked Radarr source files — re-check against Radarr's `develop` branch when a new Radarr major lands (unverified beyond the doc's reverse engineering) |

Claims labeled community-sourced/unverified: Radarr's exact list-removal setting names, whether
Radarr follows slash redirects, current Radarr's If-None-Match behavior, and polling minimums.
Do not harden decisions on them without testing against a live Radarr.
