#!/usr/bin/env python3
"""diag_explain_film.py — why is film X (not) served by custom list Y?

Recomputes the custom-list funnel stage by stage with plain SQL that mirrors
src/watchlistarr/services/custom_lists.py (resolve_universe -> _apply_filters
-> eligible_pool) and src/watchlistarr/services/radarr.py (serialize_custom_list),
and prints the first stage where the film drops out. Read-only: SQLite opened
with ``file:...?mode=ro``; the optional live probe is a plain GET.

Stdlib only — runs without the project venv.

Example (from repo root):
    python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_explain_film.py \
        --db ./data/watchlistarr.db --list house --tmdb 603

Exit codes: 0 = film is served and Radarr-visible · 1 = film drops out
somewhere (explanation printed) · 2 = cannot open DB / unknown custom list.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

EPOCH = datetime(1970, 1, 1)


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


def parse_dt(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def parse_interval(value: object) -> timedelta | None:
    # SQLAlchemy Interval on SQLite stores epoch + timedelta as a DATETIME
    # string ("1970-01-08 00:00:00.000000" == 7 days). Invert it.
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt - EPOCH


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def list_label(conn: sqlite3.Connection, list_id: int) -> str:
    row = conn.execute(
        "SELECT l.slug, l.source_type, u.letterboxd_username AS username "
        "FROM lists l JOIN users u ON u.id = l.user_id WHERE l.id = ?",
        (list_id,),
    ).fetchone()
    if row is None:
        return f"list #{list_id} (missing)"
    slug = "watchlist" if row["source_type"] == "watchlist" else row["slug"]
    return f"{row['username']}/{slug}"


def cl_slug(conn: sqlite3.Connection, cl_id: int) -> str:
    row = conn.execute("SELECT slug FROM custom_lists WHERE id = ?", (cl_id,)).fetchone()
    return f"cl:{row['slug']}" if row else f"cl:#{cl_id} (missing)"


def sources_for(conn: sqlite3.Connection, cl_id: int, role: str) -> tuple[list[int], list[int]]:
    list_ids = [
        r[0]
        for r in conn.execute(
            "SELECT list_id FROM custom_list_sources "
            "WHERE custom_list_id = ? AND role = ? AND list_id IS NOT NULL",
            (cl_id, role),
        )
    ]
    cl_ids = [
        r[0]
        for r in conn.execute(
            "SELECT source_custom_list_id FROM custom_list_sources "
            "WHERE custom_list_id = ? AND role = ? AND source_custom_list_id IS NOT NULL",
            (cl_id, role),
        )
    ]
    return list_ids, cl_ids


def in_list(conn: sqlite3.Connection, list_id: int, tmdb: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM list_items WHERE list_id = ? AND tmdb_id = ?", (list_id, tmdb)
        ).fetchone()
        is not None
    )


def in_custom_list(conn: sqlite3.Connection, cl_id: int, tmdb: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM custom_list_items WHERE custom_list_id = ? AND tmdb_id = ?",
            (cl_id, tmdb),
        ).fetchone()
        is not None
    )


def served_order(conn: sqlite3.Connection, cl: sqlite3.Row) -> list[int]:
    """Mirror of serialize_custom_list (services/radarr.py:32-56): inner join
    films, snapshot mode freezes position order, non-snapshot RATING_DESC
    re-sorts at serve time, LIMIT max_items."""
    snapshot_mode = cl["snapshot_interval"] is not None
    if not snapshot_mode and cl["sort_order"] == "rating_desc":
        order = ("(f.letterboxd_avg_rating IS NULL), f.letterboxd_avg_rating DESC, cli.position")
    else:
        order = "cli.position, cli.tmdb_id"
    sql = (
        "SELECT cli.tmdb_id FROM custom_list_items cli "
        "JOIN films f ON f.tmdb_id = cli.tmdb_id "
        f"WHERE cli.custom_list_id = ? ORDER BY {order}"
    )
    params: tuple = (cl["id"],)
    if cl["max_items"] is not None:
        sql += " LIMIT ?"
        params = (cl["id"], cl["max_items"])
    return [r[0] for r in conn.execute(sql, params)]


def section(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 60 - len(title)))


def main() -> int:  # noqa: PLR0912, PLR0915 — linear funnel, deliberately verbose
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="./data/watchlistarr.db", help="path to SQLite DB file")
    parser.add_argument("--list", required=True, dest="slug", help="custom list slug")
    parser.add_argument("--tmdb", required=True, type=int, help="TMDB id of the film")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080",
        help="base URL for the optional live /lists/{slug}/ probe (failure is non-fatal)",
    )
    args = parser.parse_args()

    conn = open_db_ro(args.db)
    now = utcnow_naive()
    tmdb = args.tmdb

    cl = conn.execute("SELECT * FROM custom_lists WHERE slug = ?", (args.slug,)).fetchone()
    if cl is None:
        known = [r[0] for r in conn.execute("SELECT slug FROM custom_lists ORDER BY slug")]
        print(f"CANNOT ANALYZE: no custom list with slug {args.slug!r}. Known: {known}",
              file=sys.stderr)
        return 2

    section(f"[1] custom list '{args.slug}'")
    rot_iv = parse_interval(cl["rotation_interval"])
    snap_iv = parse_interval(cl["snapshot_interval"])
    print(f"id={cl['id']} op={cl['op']} sort_order={cl['sort_order']} "
          f"max_items={cl['max_items']}")
    print(f"rotation_enabled={bool(cl['rotation_enabled'])} rotation_interval={rot_iv} "
          f"batch={cl['rotation_batch_size']} last_rotated_at={cl['last_rotated_at']}")
    print(f"snapshot_interval={snap_iv} last_snapshot_at={cl['last_snapshot_at']}")

    section(f"[2] film {tmdb} in films table")
    film = conn.execute("SELECT * FROM films WHERE tmdb_id = ?", (tmdb,)).fetchone()
    if film is None:
        print("NOT in films — the film was never scraped/resolved. It cannot appear in any\n"
              "list_items (FK) and the Radarr serialization inner-joins films, so it is\n"
              "unservable until a scrape resolves it.")
        print("\nVERDICT: drops out at stage 2 (no films row).")
        return 1
    print(f"'{film['title']}' ({film['year']}) rating={film['letterboxd_avg_rating']} "
          f"imdb_id={film['imdb_id']} slug={film['letterboxd_slug']}")

    section("[3] include sources (resolve_universe)")
    inc_lists, inc_cls = sources_for(conn, cl["id"], "include")
    memberships: list[tuple[str, bool]] = []
    for lid in inc_lists:
        memberships.append((list_label(conn, lid), in_list(conn, lid, tmdb)))
    for cid in inc_cls:
        memberships.append((cl_slug(conn, cid), in_custom_list(conn, cid, tmdb)))
    for label, member in memberships:
        print(f"  {'IN ' if member else 'OUT'}  {label}")
    if not memberships:
        print("  no include sources at all — universe is empty by definition")
        print("\nVERDICT: drops out at stage 3 (no include sources).")
        return 1
    hits = [m for _, m in memberships]
    included = any(hits) if cl["op"] == "union" else all(hits)
    print(f"op={cl['op']} -> {'INCLUDED' if included else 'NOT included'}")
    print("note: custom-list sources are read from the source's MATERIALIZED "
          "custom_list_items,\nnot its recomputed pool (custom_lists.py:_items_by_custom_list).")
    if not included:
        print(f"\nVERDICT: drops out at stage 3 (include {cl['op']} does not cover it).")
        return 1

    section("[4] subtract sources")
    sub_lists, sub_cls = sources_for(conn, cl["id"], "subtract")
    subtracted_by = [list_label(conn, lid) for lid in sub_lists if in_list(conn, lid, tmdb)]
    subtracted_by += [cl_slug(conn, cid) for cid in sub_cls if in_custom_list(conn, cid, tmdb)]
    print(f"subtract sources: {len(sub_lists) + len(sub_cls)}; hits: {subtracted_by or 'none'}")
    if subtracted_by:
        print(f"\nVERDICT: drops out at stage 4 (subtracted by {', '.join(subtracted_by)}).")
        return 1

    section("[5] excluded watchers")
    excluded_uids = [
        r[0]
        for r in conn.execute(
            "SELECT user_id FROM custom_list_excluded_watchers WHERE custom_list_id = ?",
            (cl["id"],),
        )
    ]
    watched_by = [
        r[0]
        for r in conn.execute(
            "SELECT u.letterboxd_username FROM watched_films wf "
            "JOIN users u ON u.id = wf.user_id "
            "WHERE wf.tmdb_id = ? AND wf.user_id IN (%s)"
            % ",".join("?" * len(excluded_uids)),
            (tmdb, *excluded_uids),
        )
    ] if excluded_uids else []
    print(f"excluded watcher user_ids: {excluded_uids or 'none'}; watched by: "
          f"{watched_by or 'none'}")
    if watched_by:
        print(f"\nVERDICT: drops out at stage 5 (watched by excluded watcher "
              f"{', '.join(watched_by)}).")
        return 1

    section("[6] static filters (_apply_filters)")
    # Year window: year_last_n (clamped >=1) overrides min/max_year.
    if cl["year_last_n"] is not None:
        last_n = max(1, cl["year_last_n"])
        year_min: int | None = now.year - last_n + 1
        year_max: int | None = now.year
        print(f"year_last_n={cl['year_last_n']} -> window [{year_min}, {year_max}]")
    else:
        year_min, year_max = cl["min_year"], cl["max_year"]
        print(f"year window: [{year_min}, {year_max}]")
    # SQL comparison semantics: NULL rating/year fails any bound.
    if cl["min_rating"] is not None and (
        film["letterboxd_avg_rating"] is None
        or film["letterboxd_avg_rating"] < cl["min_rating"]
    ):
        print(f"\nVERDICT: drops out at stage 6 — rating "
              f"{film['letterboxd_avg_rating']} < min_rating {cl['min_rating']} "
              "(NULL rating also fails; consider scripts/backfill_ratings.py).")
        return 1
    if cl["max_rating"] is not None and (
        film["letterboxd_avg_rating"] is None
        or film["letterboxd_avg_rating"] > cl["max_rating"]
    ):
        print(f"\nVERDICT: drops out at stage 6 — rating above max_rating {cl['max_rating']}.")
        return 1
    if year_min is not None and (film["year"] is None or film["year"] < year_min):
        print(f"\nVERDICT: drops out at stage 6 — year {film['year']} < {year_min} "
              "(NULL year also fails).")
        return 1
    if year_max is not None and (film["year"] is None or film["year"] > year_max):
        print(f"\nVERDICT: drops out at stage 6 — year {film['year']} > {year_max}.")
        return 1
    print("rating/year filters: PASS")

    # Added-date window: added_last_n_days overrides added_after/added_before.
    if cl["added_last_n_days"] is not None:
        added_after: datetime | None = now - timedelta(days=cl["added_last_n_days"])
        added_before: datetime | None = None
    else:
        added_after = parse_dt(cl["added_after"])
        added_before = parse_dt(cl["added_before"])
    if added_after is not None or added_before is not None:
        print(f"added window: after={added_after} before={added_before}")
        in_inc_lists = any(in_list(conn, lid, tmdb) for lid in inc_lists)
        if in_inc_lists:
            # Must have at least one list_items row in an include list inside the window.
            placeholders = ",".join("?" * len(inc_lists))
            rows = conn.execute(
                f"SELECT list_id, added_at FROM list_items "
                f"WHERE tmdb_id = ? AND list_id IN ({placeholders})",
                (tmdb, *inc_lists),
            ).fetchall()
            ok = False
            for r in rows:
                added_at = parse_dt(r["added_at"])
                if added_at is None:
                    continue
                if added_after is not None and added_at < added_after:
                    continue
                if added_before is not None and added_at > added_before:
                    continue
                ok = True
            print(f"list_items added_at rows in include lists: "
                  f"{[(r['list_id'], r['added_at']) for r in rows]}")
            if not ok:
                print("\nVERDICT: drops out at stage 6 — no include-list membership inside "
                      "the added-date window.")
                return 1
            print("added filter: PASS (via include-list added_at)")
        elif inc_cls:
            print("added filter: PASS unfiltered — film reaches this list only via a "
                  "custom-list source; those have no per-source added_at "
                  "(custom_lists.py:199-229, documented limitation).")
        else:
            print("added filter: no include-list membership and no custom-list sources — "
                  "unexpected after stage 3; treating as PASS.")
    else:
        print("added filter: not configured")

    section("[7] pool verdict")
    print("Film is in the eligible pool (universe minus subtract/watched, all filters pass).")

    section("[8] served now? (custom_list_items + serialize semantics)")
    item = conn.execute(
        "SELECT position, served_since FROM custom_list_items "
        "WHERE custom_list_id = ? AND tmdb_id = ?",
        (cl["id"], tmdb),
    ).fetchone()
    items_total = conn.execute(
        "SELECT COUNT(*) FROM custom_list_items WHERE custom_list_id = ?", (cl["id"],)
    ).fetchone()[0]
    order = served_order(conn, cl)
    if item is not None:
        print(f"IN custom_list_items: position={item['position']} "
              f"served_since={item['served_since']} (table holds {items_total} items)")
        if tmdb in order:
            print(f"AND inside the served window (payload of {len(order)} items).")
            if film["imdb_id"] is None:
                print("\nVERDICT: served in JSON but imdb_id is NULL -> the key is omitted and "
                      "Radarr's StevenLuParser DISCARDS it. Fix: uv run python "
                      "scripts/backfill_imdb.py. See `radarr-integration-reference`.")
                return 1
            print("\nVERDICT: SERVED and Radarr-visible.")
            return 0
        print(f"\nVERDICT: materialized but OUTSIDE the served window — max_items="
              f"{cl['max_items']} truncates at serve time with sort_order={cl['sort_order']} "
              f"(snapshot_mode={cl['snapshot_interval'] is not None}).")
        return 1

    print(f"NOT in custom_list_items ({items_total} other items are).")
    section("[9] why not materialized: rotation / snapshot state")
    if snap_iv is not None:
        last = parse_dt(cl["last_snapshot_at"])
        nxt = (last + snap_iv) if last else None
        print(f"snapshot mode: full refresh every {snap_iv}; last={last}; next eligible={nxt}")
        print("Snapshot prevails over rotation (custom_lists.py:rotation_tick). The film joins "
              "at the next snapshot refresh IF it wins a slot under sort_order/max_items.")
    elif cl["rotation_enabled"] and rot_iv is not None:
        last = parse_dt(cl["last_rotated_at"])
        nxt = (last + rot_iv) if last else None
        print(f"rotation: every {rot_iv}, batch={cl['rotation_batch_size']}; last={last}; "
              f"next eligible={nxt}")
        if cl["sort_order"] != "random":
            print(f"CAUTION: sort_order={cl['sort_order']} picks deterministically from the "
                  "pool (_choose_from_pool) — a film that never ranks inside the batch can "
                  "wait indefinitely.")
    else:
        print("No rotation and no snapshot: items only change on recalculate() — i.e. when the "
              "custom list is edited via PUT /api/v1/custom-lists/{slug} — or at init. "
              "The pool film will NOT be pulled in automatically.")
    print("\nVERDICT: eligible but not currently materialized/served.")
    # Optional live probe (non-fatal).
    section("[opt] live probe")
    probe_url = f"{args.url.rstrip('/')}/lists/{args.slug}/"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(probe_url, method="GET"), timeout=5
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        live_ids = [it.get("tmdb_id") for it in payload]
        print(f"GET {probe_url} -> {len(live_ids)} items; film present: {tmdb in live_ids}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"live probe skipped ({probe_url}: {exc})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
