#!/usr/bin/env python3
"""diag_db_health.py — read-only health check of the watchlistarr SQLite DB.

Checks: SQLite integrity, alembic head, per-table row counts, orphan rows
invisible to Radarr, films missing imdb_id, stuck RUNNING scrape_runs, and
lists whose last sync errored. Never writes: the DB is opened with SQLite
URI mode ``file:...?mode=ro``.

Stdlib only (sqlite3/argparse/datetime) — runs without the project venv.

Example (from repo root, against the compose-mounted DB):
    python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_db_health.py \
        --db ./data/watchlistarr.db

Exit codes: 0 = healthy · 1 = findings printed · 2 = cannot open the DB.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Latest alembic revision id. Source of truth: the migration file in
# alembic/versions/ whose `revision` value no other file lists as its
# `down_revision`. Update this constant when a new migration lands:
#   ls alembic/versions/ | sort | tail -1
# (Do NOT use `grep -h "^revision" ... | sort | tail -1`: files 0001/0002 use
# single quotes and 0003+ double quotes, and `"` sorts before `'`, so that
# pipeline wrongly returns '0002'.)
EXPECTED_ALEMBIC_HEAD = "0009"  # 0009_custom_list_sources_polymorphic.py (as of 2026-07, v1.5.2)

# All application tables as of migration 0009 (see src/watchlistarr/models/*.py).
APP_TABLES = [
    "users",
    "films",
    "lists",
    "list_items",
    "watched_films",
    "viewing_logs",
    "scrape_runs",
    "custom_lists",
    "custom_list_sources",
    "custom_list_items",
    "custom_list_excluded_watchers",
]


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
    # SQLAlchemy's SQLite DATETIME stores naive UTC "YYYY-MM-DD HH:MM:SS.ffffff".
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt.replace(tzinfo=None)


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def section(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 60 - len(title)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="./data/watchlistarr.db", help="path to SQLite DB file")
    parser.add_argument(
        "--stuck-hours",
        type=float,
        default=2.0,
        help="RUNNING scrape_runs older than this many hours count as stuck (default 2)",
    )
    args = parser.parse_args()

    conn = open_db_ro(args.db)
    findings: list[str] = []
    now = utcnow_naive()

    section("SQLite integrity")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    print(f"integrity_check: {integrity}")
    print(f"quick_check:     {quick}")
    if integrity != "ok" or quick != "ok":
        findings.append("SQLite integrity check failed — restore from backup before anything else")
    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"foreign_key_check: {len(fk_violations)} violation(s)")
    for row in fk_violations[:10]:
        print(f"  table={row[0]} rowid={row[1]} references={row[2]}")
        findings.append(f"FK violation in {row[0]} (rowid {row[1]} -> {row[2]})")

    section("Alembic revision")
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        current = version[0] if version else None
    except sqlite3.OperationalError:
        current = None
    print(f"current: {current}   expected head: {EXPECTED_ALEMBIC_HEAD}")
    if current != EXPECTED_ALEMBIC_HEAD:
        findings.append(
            f"alembic_version={current!r} != expected head {EXPECTED_ALEMBIC_HEAD!r} "
            "(stale DB, or this script's constant needs updating — see comment at top)"
        )

    section("Row counts")
    for table in APP_TABLES:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            print(f"{table:32s} {count}")
        except sqlite3.OperationalError as exc:
            print(f"{table:32s} MISSING ({exc})")
            findings.append(f"table {table} missing or unreadable")

    section("Orphan rows (invisible to Radarr — serialization inner-joins films)")
    orphan_list_items = conn.execute(
        "SELECT COUNT(*) FROM list_items li "
        "LEFT JOIN films f ON f.tmdb_id = li.tmdb_id WHERE f.tmdb_id IS NULL"
    ).fetchone()[0]
    orphan_cl_items = conn.execute(
        "SELECT COUNT(*) FROM custom_list_items cli "
        "LEFT JOIN films f ON f.tmdb_id = cli.tmdb_id WHERE f.tmdb_id IS NULL"
    ).fetchone()[0]
    orphan_watched = conn.execute(
        "SELECT COUNT(*) FROM watched_films wf "
        "LEFT JOIN films f ON f.tmdb_id = wf.tmdb_id WHERE f.tmdb_id IS NULL"
    ).fetchone()[0]
    print(f"list_items without films row:        {orphan_list_items}")
    print(f"custom_list_items without films row: {orphan_cl_items}")
    print(f"watched_films without films row:     {orphan_watched}  (INFO — see note)")
    if orphan_list_items:
        findings.append(f"{orphan_list_items} list_items rows have no films row (dropped at serve)")
    if orphan_cl_items:
        findings.append(
            f"{orphan_cl_items} custom_list_items rows have no films row (dropped at serve)"
        )
    print(
        "note: watched_films.tmdb_id has NO FK to films (models/watched_films.py) — RSS can\n"
        "record a watch before the film is ever resolved. Exclusion-by-watched still works on\n"
        "the raw tmdb_id, so this count is informational, not a failure."
    )

    section("Films missing imdb_id (Radarr drops items without imdb_id)")
    missing_imdb = conn.execute("SELECT COUNT(*) FROM films WHERE imdb_id IS NULL").fetchone()[0]
    total_films = conn.execute("SELECT COUNT(*) FROM films").fetchone()[0]
    print(f"{missing_imdb} of {total_films} films have imdb_id NULL")
    if missing_imdb:
        findings.append(
            f"{missing_imdb} films lack imdb_id — served but ignored by Radarr; "
            "backfill with: uv run python scripts/backfill_imdb.py"
        )

    section(f"Stuck scrape_runs (status='running' older than {args.stuck_hours}h)")
    cutoff = now - timedelta(hours=args.stuck_hours)
    stuck = conn.execute(
        "SELECT id, source, target_id, started_at FROM scrape_runs "
        "WHERE status = 'running' ORDER BY started_at"
    ).fetchall()
    stuck_old = [r for r in stuck if (parse_dt(r["started_at"]) or now) < cutoff]
    print(f"{len(stuck)} RUNNING total, {len(stuck_old)} older than cutoff")
    for row in stuck_old[:10]:
        print(f"  run #{row['id']} source={row['source']} target={row['target_id']} "
              f"started={row['started_at']}")
    if stuck_old:
        findings.append(
            f"{len(stuck_old)} scrape_runs stuck in RUNNING — a restart marks them ERROR "
            "(services/scrape/audit.py:fail_interrupted_runs); if the app IS running, "
            "a job is hung"
        )

    section("Lists with last_sync_status = 'error'")
    err_lists = conn.execute(
        "SELECT l.id, l.slug, l.enabled, l.last_synced_at, u.letterboxd_username "
        "FROM lists l JOIN users u ON u.id = l.user_id "
        "WHERE l.last_sync_status = 'error' ORDER BY u.letterboxd_username, l.slug"
    ).fetchall()
    print(f"{len(err_lists)} list(s) in error state")
    for row in err_lists[:20]:
        print(f"  {row['letterboxd_username']}/{row['slug']} (id={row['id']}, "
              f"enabled={bool(row['enabled'])}, last_synced_at={row['last_synced_at']})")
    if err_lists:
        findings.append(
            f"{len(err_lists)} lists have last_sync_status='error' — check scrape_runs.error "
            "for the failing run and /api/v1/activity?level=ERROR"
        )

    section("Verdict")
    if not findings:
        print("OK — no findings.")
        return 0
    for i, f in enumerate(findings, 1):
        print(f"[{i}] {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
