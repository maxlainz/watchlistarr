---
name: letterboxd-scraping-reference
description: Everything about scraping Letterboxd in watchlistarr — the URL surface (profile validation, /lists/, /list/{slug}/, /watchlist/, /films/, /film/{slug}/, /rss/), the fragile HTML selectors and what breaks (loudly vs silently) when Letterboxd changes its markup, the O(2)-fetch incremental-scrape trick, RSS guid/namespace parsing, TMDB/IMDb resolution from film pages, the real (per-client, NOT global) rate limiting, Cloudflare 403 semantics, anti-bot etiquette, the LETTERBOXD_OFFLINE kill-switch, and the tests/fixtures/ specimen inventory. Use when touching services/letterboxd/*, services/scrape/*, when a scrape returns 0 items, when a selector seems broken, when investigating 403s, or when adding a new Letterboxd page type. NOT for the Radarr JSON contract or ETag behavior → use `radarr-integration-reference`. NOT for scheduling policy, job intervals, or the anti-flap canonical formula → use `watchlistarr-architecture-contract` (scheduler + invariants) and `watchlistarr-config-and-flags` (interval env vars). NOT for historical incident stories → use `watchlistarr-failure-archaeology`.
---

# Letterboxd scraping reference

Letterboxd has no public API. watchlistarr lives entirely off public HTML pages and the per-user
RSS feed. This file is the single home for URLs, selectors, parsing semantics, rate-limit reality,
and fixtures. Parsers live in `src/watchlistarr/services/letterboxd/`; orchestration lives in
`src/watchlistarr/services/scrape/`. All anchors below verified as of 2026-07 (v1.5.2, HEAD `4439c17`).

## When to use

- You are editing any file under `src/watchlistarr/services/letterboxd/` or `src/watchlistarr/services/scrape/`.
- A sync log shows `slugs=0`, `total=0`, or `film.skipped` and you suspect Letterboxd changed its HTML.
- You need to know which URL a job hits, what selector parses it, and what happens when that selector misses.
- You are writing or updating a fixture in `tests/fixtures/` and need to know what it must be a specimen of.
- You are investigating a Cloudflare 403 or planning request-volume changes.

## When NOT to use

- Served JSON shape, `imdb_id` omission, ETag/304, StevenLuParser behavior → `radarr-integration-reference`.
- Which jobs run when, interval defaults/overrides, the anti-flap removal formula verbatim → `watchlistarr-architecture-contract` and `watchlistarr-config-and-flags`.
- The TMDB-remap crash story or the "database is locked" story in full → `watchlistarr-failure-archaeology`.
- Fixing the concurrency gap in rate limiting (open work) → `watchlistarr-hardening-campaign` track A.

## URL surface

All paths are relative to `https://letterboxd.com` (`client.py:14`). Every request goes through
`LetterboxdClient.get()` — never call httpx directly.

| Path | Purpose | Caller (file:line) |
|---|---|---|
| `/{username}/` | Validate user exists: expect 200 + response header `x-letterboxd-type: Member` | `services/scrape/initial_run.py:30,35` (called from `routes/api/v1.py:512` on user creation) |
| `/{username}/lists/` + `/lists/page/{N}/` | Discover all public lists created by the user | `services/scrape/discovery.py:22` |
| `/{username}/list/{slug}/` + `page/{N}/` | List items, user-defined order (full sync iterates all pages) | `services/scrape/lists.py:21-27,44-57` |
| `/{username}/list/{slug}/by/added-earliest/page/{N}/` | Oldest-added-first sort; its LAST page = newest additions (incremental sync) | `services/scrape/lists.py:24,121-125` |
| `/{username}/watchlist/` + `page/{N}/` | Watchlist items; default order is newest-added-first | `services/scrape/watchlist.py:22-23` |
| `/{username}/films/` | Watched-films page 1 — backstop for RSS-missed viewings | `services/scrape/films_backstop.py:27`, `services/scrape/anti_flap.py:74` |
| `/film/{slug}/` | Film page — the ONLY place to get the TMDB id | `services/scrape/film_resolver.py:116` |
| `/{username}/rss/` | Per-user RSS feed of watch/review events | `services/scrape/rss_watcher.py:27` |

Notes (values below marked "observed" come from the spec research in `.claude/letterboxd-lists.md`,
not from code — code never hardcodes them):

- The header check is exact: `response.headers.get("x-letterboxd-type", "") != "Member"` raises
  `UserValidationError` (`initial_run.py:35-39`). Reserved usernames (`all`, `api`, `admin`,
  `static`, `health`, `_`, `lists`) are rejected before any HTTP (`initial_run.py:15-17`; the
  RESERVED_USERNAMES rationale is owned by `watchlistarr-architecture-contract`).
- Page sizes (observed): 28 items/page for lists and watchlist, 72 for `/films/`.
- Out-of-range `/page/N/` returns **403, not 404** (observed). The code never blind-iterates: it
  parses total pages from page 1 first (`lists.py:52-53`, `watchlist.py:104`).
- `/films/page/N/` for N≥2 is Cloudflare-blocked (observed) — only page 1 is ever fetched.
- `/film/{slug}/json/` is behind a Cloudflare challenge (observed) — never use it; parse the HTML page.
- Watchlist `/by/*` sorts are all 403 (observed); list `/by/added-earliest/` works — this asymmetry
  is why watchlist-incremental and list-incremental differ (see incremental trick below).

## HTML selectors — the fragile crown jewels

Every selector, where it is parsed, which fixture exercises it, and the blast radius when
Letterboxd changes the markup. "Silent" means no exception and no ERROR scrape run — only info logs.

| Selector / pattern | Parser | Fixture | Failure behavior when it breaks |
|---|---|---|---|
| `article.list-summary[data-film-list-id]` | `services/letterboxd/lists.py:15` (`parse_lists_index`) | `lists_index.html` | **Silent, high blast radius**: discovery returns `[]`, and `discovery.py:81-89` then sets `enabled=False` on every enabled list whose `letterboxd_list_id` is no longer seen — jobs vanish on next `sync_jobs()`, raw-list Radarr routes start 404ing. Watch for `discovery.disabled_missing` log storms. |
| `h2.name a` (slug+name inside the article) | `services/letterboxd/lists.py:17-25` | `lists_index.html` | Silent skip of that article (`continue`) — same downstream effect as above for the affected lists. |
| `.content-reactions-strip .value` (film count) | `services/letterboxd/lists.py:26-30` | `lists_index.html` (the "Empty List" article has none → count 0) | Silent, cosmetic: `film_count=0` in discovery; full sync overwrites it with `len(resolved)` anyway (`scrape/lists.py:96`). |
| `div.react-component[data-item-slug]` (list/watchlist items) | `services/letterboxd/lists.py:45` (`parse_list_items`) | `watchlist_p1.html` | **Silent, worst blast radius**: full sync scrapes 0 items, every existing `list_items` row becomes a removal candidate; the anti-flap counter (threshold default 3, see `watchlistarr-architecture-contract`) is the ONLY brake before mass removal empties the Radarr payload. Watch for `slugs=0` in `list.full_sync` / `watchlist.full_sync` logs. |
| `li.griditem` → `div.react-component[data-item-slug]` (/films/ items) | `services/letterboxd/films.py:11-12` (`parse_films_page`) | `films_p1.html` | Silent: films-backstop inserts nothing and anti-flap step 2 loses its watched-confirmation source — removals degrade to the slow counter path. |
| `div.pagination` + last `/page/(\d+)/` href | `services/letterboxd/lists.py:54-65` (`parse_total_pages`, regex at `lists.py:9`) | `pagination_block.html` (23 pages), `pagination_single.html` (no block → 1) | **Silent, partial blast radius**: returns 1, so full sync only fetches page 1 — items on pages 2+ look removed (anti-flap counters start for them), and list-incremental skips its last-page fetch so tail additions go unseen until the selector is fixed. Distinguish from the item-selector break: here page-1 items still resolve. |
| `body[data-tmdb-id]` / `body[data-tmdb-type]` | `services/letterboxd/film_page.py:16-23` | `film_page_movie.html` (movie), `film_page_tv.html` (tv) | Missing attributes → `tmdb_id=None` → `resolve_films` skips the slug with info log `film.skipped` (`film_resolver.py:124-127`): **silent** — new films never enter the DB; already-cached films keep serving. A page with no `<body>` at all raises `ValueError` (`film_page.py:17-18`) → **loud**: scrape run ERROR, list marked `last_sync_status=error`. |
| IMDb link regex `imdb\.com/title/(tt\d{7,10})` (searched over raw HTML) | `services/letterboxd/film_page.py:11,38-41` | `film_page_movie.html` (http:// variant; https covered by `test_film_page.py:87`) | Silent: film persists with `imdb_id=NULL` → Radarr discards the item (see `radarr-integration-reference`), and the slug never satisfies the resolver cache condition, so it is re-fetched on every resolve (extra load). |
| JSON-LD `aggregateRating.ratingValue` (`<script type="application/ld+json">`, tolerates CDATA-comment wrapping and string values) | `services/letterboxd/film_page.py:56-82` | `film_page_movie.html` (ratingValue 4.53) | Silent: `letterboxd_avg_rating=NULL` → rating-based custom-list sorts degrade and, like the imdb miss, the cache condition (`film_resolver.py:108`) keeps forcing re-fetches. |
| `x-letterboxd-type: Member` response header | `services/scrape/initial_run.py:35-39` | none (mocked headers in `tests/integration/test_scrape_initial_run.py`) | **Loud**: `UserValidationError`, surfaced as an API error at user creation. |

House law (`.claude/rules.md` §"Scraping de Letterboxd"): when a selector fails, **fail loudly and
log enough context to repair it — never guess an alternative structure**. Note the table above shows
several paths where the current code degrades silently instead; treat any `slugs=0` / mass
`discovery.disabled_missing` as a selector break until proven otherwise. Loud selector-drift
detection is open work — see `watchlistarr-hardening-campaign`.

## The incremental-scrape trick (additions in O(2) page fetches)

Definitions: a **full sync** fetches every page and may remove items (via anti-flap); an
**incremental sync** fetches a fixed small number of pages and only ever adds/refreshes.

- **Watchlist incremental** (`scrape/watchlist.py:180-209`): the default watchlist order is
  newest-added-first (observed), so page 1 alone contains the latest additions. One fetch.
- **List incremental** (`scrape/lists.py:108-153`): custom-list default order is the owner's manual
  order, and the useful `/by/added/` sort is Cloudflare-blocked (observed). Workaround: fetch
  page 1 of the default order (also yields `total_pages`), then fetch the **last** page of
  `/by/added-earliest/` — oldest-first means the last page holds the newest additions. Two fetches;
  single-page lists skip the second (`lists.py:121-127`). Results are concatenated and de-duplicated
  by slug (`lists.py:129-135`).
- New slugs still cost **one `/film/{slug}/` fetch each** inside `resolve_films` — the O(2) bound is
  for detection, not resolution.

Position semantics (`scrape/watchlist.py:26-77`, `_upsert_items`, shared by list sync):

- Full sync passes `reassign_positions=True`: every item's `position` is rewritten to its index in
  the scraped order.
- Incremental passes `reassign_positions=False`: existing positions are left untouched (the scraped
  slice does not reflect real list positions) and new items are appended at `max(position)+1`
  (`watchlist.py:48,58-62`). Order self-heals at the next full sync.
- Every scrape that sees an item refreshes `last_seen_at` and resets `pending_removal_count = 0`
  (`watchlist.py:75-76`). Incremental syncs never remove anything.

## RSS feed

Feed: `GET /{username}/rss/` (`scrape/rss_watcher.py:27`), parsed with feedparser
(`services/letterboxd/rss.py`). Item window is small — ~20–50 recent items, no pagination
(observed) — which is exactly why the `/films/` page-1 backstop exists.

| Rule | Code |
|---|---|
| Accept guids prefixed `letterboxd-watch-`, `letterboxd-review-`; ignore `letterboxd-list-`; anything else is dropped | `rss.py:13-14,31-34` |
| Dedup by guid against `viewing_logs.letterboxd_guid` — already-seen guids are skipped | `rss_watcher.py:43-51,66-67` |
| `tmdb:movieId` (feedparser key `tmdb_movieid`) is required; items without it (TV shows carry `tmdb:tvId` instead) are skipped with info log `rss.skipped_no_movie_id` | `rss.py:36-48` |
| `letterboxd:watchedDate` parsed as `YYYY-MM-DD`; missing or malformed → item skipped | `rss.py:50-56` |
| `letterboxd:memberRating` → optional float; `letterboxd:memberLike` → `Yes`/`No` bool; review-ness inferred from the guid prefix | `rss.py:58-66,82` |
| New events insert `viewing_logs` rows and upsert `watched_films` with `source='rss'` | `rss_watcher.py:69-96` |

**RSS does NOT trigger rotation.** `.claude/letterboxd-rss.md` claims the watcher "dispara la
rotación" — wrong as of 2026-07 (see the standing errata table in `watchlistarr-docs-and-writing`).
`poll_rss_for_user` only writes `viewing_logs` + `watched_films`; rotation happens in the
independent `rotation-tick` scheduler job, and watched-status is consulted there and by anti-flap.
The same doc's "Botón Refrescar" mitigation is also fiction — no per-list refresh button exists.

## Film page resolution (`/film/{slug}/`)

`resolve_films` (`services/scrape/film_resolver.py:75-166`) is the only path from slug to TMDB id.
Pipeline: short read session (cache films whose `imdb_id` AND `letterboxd_avg_rating` are both
non-null, `film_resolver.py:108`) → pure-HTTP fetch of uncached slugs → short write session. No
HTTP ever runs inside the write transaction (the "database is locked" lesson — full story in
`watchlistarr-failure-archaeology`).

- Gate: only `tmdb_type == "movie"` with a non-null `data-tmdb-id` is persisted; TV and id-less
  pages are skipped with log `film.skipped` (`film_resolver.py:124-127`).
- Extracted per page: `data-tmdb-id`, `data-tmdb-type`, title+year from `og:title` ("Title (YYYY)"),
  imdb id via the regex, average rating via JSON-LD (`film_page.py`).
- Remap survival: when Letterboxd remaps a slug to a different TMDB entry, the old row's slug is
  tombstoned to `{slug}--superseded-{tmdb_id}` and a conflicting `imdb_id` is yielded to the new
  row (`film_resolver.py:37-72`), so full syncs no longer crash on the UNIQUE constraints. Root
  cause and incident history: `watchlistarr-failure-archaeology` (TMDB-remap incident, v1.5.1).

## Rate limiting — what the code actually does

Read `services/letterboxd/client.py` before believing any doc:

- **Per-client-instance** `asyncio.Lock` + minimum 2.0 s spacing between requests
  (`client.py:15,46,67-70,77-83`). The lock serializes requests **within one `LetterboxdClient`
  only**.
- **There is NO per-domain or global rate limit.** Each scheduler job wrapper constructs its own
  client (`scheduler.py:260,279,310`), as do the initial run and the toggle-triggered immediate
  sync (`services/onboarding.py:99,167`) — concurrent jobs DO hit Letterboxd in parallel. Any doc
  claiming a global limiter is wrong; closing this gap is `watchlistarr-hardening-campaign` track A.
- Retries: up to 3 attempts total, **only on 5xx**, backoff 1 s doubling (`client.py:17,85-102`).
- **403 = hard fail, no retry** (`client.py:91-93`, log `letterboxd.forbidden`). 403 is Cloudflare's
  answer for blocked UAs, blocked `/by/*` sorts, and out-of-range pages — there is no recovery
  playbook yet (campaign track A).
- Timeout 30 s (`client.py:16`); redirects followed (`client.py:41`).
- User-Agent comes from `Settings.user_agent`, default
  `watchlistarr/{__version__} (+https://github.com/maxlainz/watchlistarr)` (`config.py:46`).
  `.env.example` pins an outdated `watchlistarr/1.0.0` — do not copy that pin (errata; see
  `watchlistarr-docs-and-writing`).

## Anti-bot etiquette (house law — `.claude/rules.md` §"Scraping de Letterboxd")

1. **Identify honestly**: `watchlistarr/<version> (+repo-url)` UA; never spoof a browser, never use
   an AI-bot UA (Letterboxd's robots.txt disallows those entirely; the routes we use are allowed
   for `User-agent: *` — observed).
2. **Never parallelize requests against the same Letterboxd account.** Note this is currently
   aspiration, not reality: the per-client lock cannot see across the multiple concurrent clients
   described above. Do not make it worse; fixing it is tracked in `watchlistarr-hardening-campaign`.
3. **Fail loudly on selector breaks** — log the URL and context, never guess alternative markup.
4. **Extract minimal data**: TMDB id, title, year, imdb id, avg rating. Radarr gets everything else
   from TMDB itself; do not clone metadata.
5. Cache within a scrape cycle: persist TMDB ids and never re-resolve a fully-populated film
   (`film_resolver.py:108` is the cache condition).

## LETTERBOXD_OFFLINE kill-switch

`LETTERBOXD_OFFLINE=true` (env; `config.py:47`, listed in `.env.example:10`) makes every
`LetterboxdClient.get()` raise `LetterboxdOfflineError` before any HTTP (`client.py:20-21,63-65`).
Use it in dev/QC whenever you don't explicitly need live Letterboxd — scheduler jobs will error
(visible in scrape runs) instead of hitting the site. Immutable after boot like all env settings
(precedence rules: `watchlistarr-config-and-flags`).

## Fixtures inventory (`ls tests/fixtures/`)

Fixtures are verbatim-shaped specimens of real Letterboxd markup (trimmed). Unit tests load them
via `tests/unit/letterboxd/conftest.py`; integration tests mock HTTP with respx and feed them via
`tests/integration/conftest.py:fixture_text` (client built with `min_interval_seconds=0`). If you
change a parser, update its fixture in the same commit only when the live markup actually changed.

| File | Specimen of | Exercised by |
|---|---|---|
| `lists_index.html` | `/{user}/lists/` — 3 `article.list-summary` entries, one without a film-count strip (count→0 path) | `tests/unit/letterboxd/test_lists.py`, `tests/integration/test_scrape_discovery.py` |
| `watchlist_p1.html` | list/watchlist grid — 3 full `LazyPoster` divs with every `data-*` attribute | `test_lists.py::test_parse_list_items_returns_slugs`, `test_scrape_watchlist.py`, `test_scrape_lists.py` |
| `pagination_block.html` | grid page WITH `div.pagination`, last page 23 | `test_lists.py::test_parse_total_pages_with_block`, `test_scrape_lists.py` (multi-page full sync) |
| `pagination_single.html` | grid page WITHOUT pagination block → 1 page | `test_lists.py::test_parse_total_pages_without_block` |
| `film_page_movie.html` | `/film/{slug}/` movie (Parasite): `data-tmdb-id`/`type=movie`, `og:title`, http IMDb link, JSON-LD rating 4.53 | `tests/unit/letterboxd/test_film_page.py`, `tests/integration/test_film_resolver.py` |
| `film_page_tv.html` | `/film/{slug}/` TV (Severance): `data-tmdb-type="tv"` → must be skipped | `test_film_page.py::test_parse_film_page_tv`, resolver gate tests |
| `films_p1.html` | `/{user}/films/` page 1 — griditems plus `poster-viewingdata` rating/like blocks (which the parser ignores) | `tests/unit/letterboxd/test_films.py`, `test_scrape_watchlist.py` (backstop), `test_scrape_concurrency.py` |
| `rss_feed.xml` | RSS feed with all 4 item shapes: watch without rating, review with rating 4.5, `letterboxd-list-` item (ignored), TV watch with `tmdb:tvId` only (skipped) | `tests/unit/letterboxd/test_rss.py`, `tests/integration/test_scrape_rss.py` |

## Known doc errata in this area (do not propagate)

`.claude/letterboxd-lists.md` and `.claude/letterboxd-rss.md` are largely accurate on markup and
observed Cloudflare behavior, but wrong as of 2026-07 on three points (full standing errata table:
`watchlistarr-docs-and-writing`):

- There is **no `LETTERBOXD_USER` env var** (lists.md L9). Users are created via
  `POST /api/v1/users` and validated with `validate_username`.
- There is **no "paste a URL" fallback** for private lists (lists.md L96, L249). Lists come only
  from discovery + enable toggle; private lists are simply unsupported.
- The **RSS watcher does not trigger rotation** and there is **no per-list Refresh button**
  (rss.md L3, L150, L166). See the RSS section above for what actually happens.

## Provenance and maintenance

Everything above was verified by reading code at v1.5.2 (HEAD `4439c17`, 2026-07). Values labeled
"observed" come from the spec research recorded in `.claude/letterboxd-lists.md` /
`.claude/letterboxd-rss.md` (live-site observations, not enforceable by tests). Re-verify before
trusting:

| Fact | Re-verify with (from repo root) |
|---|---|
| URL surface / callers | `grep -rn "client.get(" src/watchlistarr/services/scrape/ src/watchlistarr/services/onboarding.py` |
| All CSS selectors | `grep -n "select" src/watchlistarr/services/letterboxd/lists.py src/watchlistarr/services/letterboxd/films.py` |
| Film-page attributes, IMDb regex, JSON-LD rating | `grep -n "data-tmdb\|_IMDB_ID_RE\|aggregateRating" src/watchlistarr/services/letterboxd/film_page.py` |
| Profile-validation header | `grep -n "x-letterboxd-type" src/watchlistarr/services/scrape/initial_run.py` |
| Rate limit / retries / 403 / timeout constants | `grep -n "MIN_INTERVAL_SECONDS\|MAX_ATTEMPTS\|TIMEOUT_SECONDS\|403" src/watchlistarr/services/letterboxd/client.py` |
| One-client-per-job reality | `grep -n "LetterboxdClient(settings" src/watchlistarr/scheduler.py src/watchlistarr/services/onboarding.py` |
| RSS guid prefixes and movieId gate | `grep -n "_ACCEPTED_PREFIXES\|_IGNORED_PREFIXES\|tmdb_movieid" src/watchlistarr/services/letterboxd/rss.py` |
| Incremental trick paths | `grep -n "by_added_earliest\|added-earliest" src/watchlistarr/services/scrape/lists.py` |
| Position semantics | `grep -n "reassign_positions\|next_new_position" src/watchlistarr/services/scrape/watchlist.py` |
| Discovery mass-disable behavior | `grep -n "disabled_missing" src/watchlistarr/services/scrape/discovery.py` |
| Kill-switch | `grep -n "letterboxd_offline" src/watchlistarr/config.py src/watchlistarr/services/letterboxd/client.py` |
| Fixtures inventory | `ls tests/fixtures/` |
| Cache condition forcing re-fetches | `grep -n "letterboxd_avg_rating is not None" src/watchlistarr/services/scrape/film_resolver.py` |

If Letterboxd changes markup: update the parser, capture a fresh specimen into the matching
fixture, and update `.claude/letterboxd-lists.md` / `letterboxd-rss.md` in the same change — all
routed through the flow in `watchlistarr-change-control`.
