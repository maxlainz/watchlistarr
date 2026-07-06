#!/usr/bin/env python3
"""diag_diff_served.py — does a live Radarr endpoint match what the DB says?

Fetches one Radarr-facing endpoint (/lists/{slug}/, /{username}/watchlist/ or
/{username}/{slug}/ — routes/api/radarr.py), recomputes the expected payload
from the DB with plain SQL that mirrors services/radarr.py (raw list:
list_items JOIN films ORDER BY position, tmdb_id; custom list: snapshot mode
freezes position order, otherwise RATING_DESC re-sorts at serve time, then
LIMIT max_items), and diffs them. Also reports items served without imdb_id
(Radarr's StevenLuParser discards those) and probes ETag stability (two GETs
must agree; If-None-Match must yield 304). Read-only: SQLite opened with
``file:...?mode=ro``; HTTP is plain GETs.

Stdlib only — runs without the project venv.

Example (from repo root):
    python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_diff_served.py \
        --db ./data/watchlistarr.db --url http://127.0.0.1:8080 --endpoint /lists/house/

Exit codes: 0 = live payload matches DB expectation and is Radarr-clean ·
1 = findings printed · 2 = cannot open the DB / cannot reach --url.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

# routes/api/radarr.py route guard: these usernames 404 unconditionally
# (services/scrape/initial_run.py:RESERVED_USERNAMES).
RESERVED_USERNAMES = {"all", "api", "admin", "static", "health", "_", "lists"}

ALLOWED_ITEM_KEYS = {"id", "tmdb_id", "title", "imdb_id"}  # schemas/radarr.py:RadarrItem


def open_db_ro(path: str) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.exists():
        print(f"CANNOT CONNECT: no file at {resolved}", file=sys.stderr)
        sys.exit(2)
    try:
        conn = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error as exc:
        print(f"CANNOT CONNECT: {resolved}: {exc}", file=sys.stderr)
        sys.exit(2)


def section(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 60 - len(title)))


def classify_endpoint(endpoint: str) -> tuple[str, dict[str, str]]:
    """Returns (kind, params); kind in {'custom', 'watchlist', 'rawlist'}."""
    parts = [p for p in endpoint.strip().strip("/").split("/") if p]
    if len(parts) == 2 and parts[0] == "lists":
        return "custom", {"slug": parts[1]}
    if len(parts) == 2 and parts[1] == "watchlist":
        return "watchlist", {"username": parts[0]}
    if len(parts) == 2:
        return "rawlist", {"username": parts[0], "slug": parts[1]}
    print(
        f"CANNOT ANALYZE: --endpoint {endpoint!r} does not match /lists/{{slug}}/, "
        "/{username}/watchlist/ or /{username}/{slug}/ (routes/api/radarr.py)",
        file=sys.stderr,
    )
    sys.exit(2)


def http_get(url: str, etag: str | None = None) -> tuple[int, str | None, bytes]:
    """GET url; returns (status, etag_header, body). 304/404 are data, not errors."""
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    if etag is not None:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("ETag"), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("ETag"), exc.read()


def expected_rows(
    conn: sqlite3.Connection, kind: str, params: dict[str, str]
) -> tuple[list[sqlite3.Row] | None, str | None]:
    """Recomputes the served rows [(tmdb_id, title, imdb_id)] from the DB.

    Returns (rows, why_404). rows=None means the route should 404 and why_404
    explains it. Mirrors services/radarr.py:serialize_list/serialize_custom_list
    and the guards in routes/api/radarr.py.
    """
    if kind == "custom":
        cl = conn.execute(
            "SELECT id, slug, sort_order, max_items, snapshot_interval "
            "FROM custom_lists WHERE slug = ?",
            (params["slug"],),
        ).fetchone()
        if cl is None:
            known = [r[0] for r in conn.execute("SELECT slug FROM custom_lists ORDER BY slug")]
            return None, f"no custom_lists row with slug {params['slug']!r} (known: {known})"
        # NOTE: custom_lists.enabled is a DEAD flag — the Radarr route never
        # checks it (routes/api/radarr.py:39-51), so no 404 for disabled here.
        snapshot_mode = cl["snapshot_interval"] is not None
        if not snapshot_mode and cl["sort_order"] == "rating_desc":
            order = (
                "(f.letterboxd_avg_rating IS NULL), f.letterboxd_avg_rating DESC, cli.position"
            )
        else:
            order = "cli.position, cli.tmdb_id"
        sql = (
            "SELECT cli.tmdb_id, f.title, f.imdb_id FROM custom_list_items cli "
            "JOIN films f ON f.tmdb_id = cli.tmdb_id "
            f"WHERE cli.custom_list_id = ? ORDER BY {order}"
        )
        args: tuple = (cl["id"],)
        if cl["max_items"] is not None:
            sql += " LIMIT ?"
            args = (cl["id"], cl["max_items"])
        print(
            f"custom list id={cl['id']} sort_order={cl['sort_order']} "
            f"max_items={cl['max_items']} snapshot_mode={snapshot_mode}"
        )
        if snapshot_mode:
            print("snapshot mode: serve order is the materialized position — frozen between "
                  "snapshot refreshes even for RATING_DESC")
        elif cl["sort_order"] == "rating_desc":
            print("RATING_DESC without snapshot: re-sorted by films.letterboxd_avg_rating at "
                  "EVERY serve (NULL ratings last, ties by position) — a rating backfill "
                  "reorders the payload and churns Radarr")
        return conn.execute(sql, args).fetchall(), None

    username = params["username"]
    if username in RESERVED_USERNAMES:
        return None, f"username {username!r} is in RESERVED_USERNAMES — route 404s by design"
    user = conn.execute(
        "SELECT id FROM users WHERE letterboxd_username = ?", (username,)
    ).fetchone()
    if user is None:
        return None, f"no users row with letterboxd_username {username!r}"
    if kind == "watchlist":
        lst = conn.execute(
            "SELECT id, enabled FROM lists WHERE user_id = ? AND source_type = 'watchlist'",
            (user["id"],),
        ).fetchone()
        label = f"{username}/watchlist"
    else:
        lst = conn.execute(
            "SELECT id, enabled FROM lists WHERE user_id = ? AND slug = ?",
            (user["id"], params["slug"]),
        ).fetchone()
        label = f"{username}/{params['slug']}"
    if lst is None:
        return None, f"no lists row for {label}"
    if not lst["enabled"]:
        return None, f"{label} exists but enabled=0 — raw-list routes 404 when disabled"
    print(f"raw list {label} (lists.id={lst['id']}, enabled=1) — served unfiltered/uncapped, "
          "ordered by position (services/radarr.py:serialize_list)")
    rows = conn.execute(
        "SELECT li.tmdb_id, f.title, f.imdb_id FROM list_items li "
        "JOIN films f ON f.tmdb_id = li.tmdb_id "
        "WHERE li.list_id = ? ORDER BY li.position, li.tmdb_id",
        (lst["id"],),
    ).fetchall()
    return rows, None


def main() -> int:  # noqa: PLR0912, PLR0915 — linear report, deliberately verbose
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="./data/watchlistarr.db", help="path to SQLite DB file")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8080", help="base URL of the running instance"
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="served path, e.g. /lists/foo/ or /user/watchlist/ or /user/some-slug/",
    )
    parser.add_argument(
        "--show", type=int, default=10, help="max diff entries to print per section (default 10)"
    )
    args = parser.parse_args()

    conn = open_db_ro(args.db)
    kind, params = classify_endpoint(args.endpoint)
    endpoint = "/" + args.endpoint.strip("/") + "/"
    full_url = args.url.rstrip("/") + endpoint
    findings: list[str] = []

    section(f"[1] Live fetch: GET {full_url}")
    try:
        status, etag, body = http_get(full_url)
    except (urllib.error.URLError, OSError) as exc:
        print(f"CANNOT CONNECT: {full_url}: {exc}", file=sys.stderr)
        return 2
    print(f"HTTP {status}, ETag: {etag}, {len(body)} bytes")

    live_items: list[dict] | None = None
    if status == 200:
        try:
            live_items = json.loads(body.decode("utf-8"))
        except ValueError as exc:
            print(f"body is not JSON: {exc}")
            findings.append("live endpoint returned 200 with a non-JSON body")
        if live_items is not None and not isinstance(live_items, list):
            findings.append(f"live payload is not a JSON array (got {type(live_items).__name__})")
            live_items = None
    elif status == 404:
        print("endpoint returned 404 — checking the DB for why (route guards below)")
    else:
        findings.append(f"unexpected HTTP status {status} from {endpoint}")

    section("[2] DB expectation (mirrors services/radarr.py)")
    rows, why_404 = expected_rows(conn, kind, params)
    if rows is None:
        print(f"DB says this endpoint SHOULD 404: {why_404}")
        if status == 404:
            print("\nVERDICT: live 404 matches DB expectation. Not a serving bug — "
                  "fix the underlying cause above if unintended.")
            # Consistent, but the operator asked about a dead endpoint: still exit 1
            # so scripted callers notice something needs attention.
            return 1
        findings.append(
            f"DB expects 404 ({why_404}) but the live endpoint returned {status} — "
            "the instance is serving from a DIFFERENT database than --db points at"
        )
    elif status == 404:
        findings.append(
            "live endpoint 404s but the DB has a servable row — likely wrong --url, a "
            "different DB file, or (raw lists) the row was disabled after your DB copy"
        )
    expected_ids = [r["tmdb_id"] for r in rows] if rows is not None else []
    if rows is not None:
        print(f"expected {len(expected_ids)} items from DB")

    if live_items is not None and rows is not None:
        section("[3] Diff live vs expected")
        live_ids = [it.get("tmdb_id") for it in live_items]
        print(f"live={len(live_ids)} expected={len(expected_ids)}")
        if len(live_ids) != len(expected_ids):
            findings.append(
                f"COUNT mismatch: live serves {len(live_ids)} items, DB expects "
                f"{len(expected_ids)}"
            )
        live_set, exp_set = set(live_ids), set(expected_ids)
        missing = [t for t in expected_ids if t not in live_set]
        extra = [t for t in live_ids if t not in exp_set]
        if missing:
            findings.append(f"{len(missing)} expected tmdb_ids MISSING from live payload")
            print(f"missing from live (first {args.show}): {missing[: args.show]}")
        if extra:
            findings.append(f"{len(extra)} live tmdb_ids NOT expected from DB")
            print(f"unexpected in live (first {args.show}): {extra[: args.show]}")
        if not missing and not extra and live_ids != expected_ids:
            first_div = next(
                i for i, (a, b) in enumerate(zip(live_ids, expected_ids)) if a != b
            )
            findings.append(
                f"ORDER mismatch: same membership, different order (first divergence at "
                f"index {first_div}: live={live_ids[first_div]} "
                f"expected={expected_ids[first_div]})"
            )
        if live_ids == expected_ids:
            print("membership and order MATCH")
        else:
            print("caveat: this script reads the DB after fetching HTTP — a scrape/rotation "
                  "landing in between produces a legitimate one-off diff. Re-run before "
                  "trusting a mismatch.")

        # Radarr item shape (schemas/radarr.py + render_payload exclude_none).
        shape_bad = [
            it
            for it in live_items
            if not isinstance(it, dict)
            or not set(it) <= ALLOWED_ITEM_KEYS
            or it.get("id") != it.get("tmdb_id")
        ]
        if shape_bad:
            findings.append(
                f"{len(shape_bad)} live items break the RadarrItem shape "
                "(keys beyond id/tmdb_id/title/imdb_id, or id != tmdb_id)"
            )
            print(f"malformed items (first {args.show}): {shape_bad[: args.show]}")

    if live_items is not None:
        section("[4] Items invisible to Radarr (no imdb_id)")
        no_imdb = [it for it in live_items if "imdb_id" not in it]
        print(f"{len(no_imdb)} of {len(live_items)} served items have no imdb_id key "
              "(render_payload omits NULLs; Radarr's StevenLuParser discards these)")
        for it in no_imdb[: args.show]:
            print(f"  tmdb {it.get('tmdb_id')}: {it.get('title')!r}")
        if no_imdb:
            findings.append(
                f"{len(no_imdb)} served items lack imdb_id — present in JSON but Radarr "
                "ignores them; backfill with: uv run python scripts/backfill_imdb.py"
            )

    if status == 200 and etag:
        section("[5] ETag stability (second GET + conditional GET)")
        try:
            status2, etag2, body2 = http_get(full_url)
            print(f"second GET: HTTP {status2}, ETag: {etag2}")
            if body2 != body:
                findings.append(
                    "payload CHANGED between two back-to-back GETs — a write landed mid-check "
                    "(scrape/rotation/snapshot); re-run to confirm, and if it changes every "
                    "time with sort_order=rating_desc and no snapshot_interval, that is the "
                    "serve-time re-sort churning Radarr"
                )
            elif etag2 != etag:
                findings.append(
                    f"same payload but ETag changed ({etag} -> {etag2}) — ETag must be a pure "
                    "function of the payload (services/radarr.py:compute_etag)"
                )
            status3, _, _ = http_get(full_url, etag=etag2)
            print(f"conditional GET (If-None-Match: {etag2}): HTTP {status3}")
            if status3 == 304:
                print("304 as expected — Radarr's polling stays cheap")
            elif body2 == body:
                findings.append(
                    f"If-None-Match returned {status3}, expected 304 "
                    "(routes/api/radarr.py:_respond compares the raw header string)"
                )
            else:
                print("(payload was already unstable; skipping the 304 verdict)")
        except (urllib.error.URLError, OSError) as exc:
            print(f"ETag probe aborted: {exc}")
            findings.append("could not complete the ETag stability probe")
    elif status == 200:
        findings.append("200 response carried NO ETag header — _respond always sets one")

    section("Verdict")
    if not findings:
        print("OK — live payload matches the DB expectation and every item is Radarr-visible.")
        return 0
    for i, f in enumerate(findings, 1):
        print(f"[{i}] {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
