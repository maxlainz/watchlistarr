#!/usr/bin/env python3
"""diag_scheduler.py — expected-vs-live scheduler jobs + per-job staleness.

Derives the EXPECTED APScheduler job ids from DB state exactly the way
src/watchlistarr/scheduler.py:sync_jobs() rebuilds them (remove-all-and-re-add
at boot and after any user/list mutation), cross-checks the live scheduler via
GET /api/v1/dashboard (best-effort: the dashboard exposes only the next 5 jobs
as pretty labels, not raw ids), and measures per-job staleness from
scrape_runs against the effective interval (per-entity DB override `or` env
default — replicating services/intervals.py, including its falsy fallthrough).
Also reports stuck RUNNING scrape_runs and lists in error state. Read-only:
SQLite opened with ``file:...?mode=ro``; HTTP is plain GETs.

Stdlib only — runs without the project venv.

Example (from repo root, against the compose-mounted DB and local instance):
    python3 .claude/skills/watchlistarr-diagnostics-and-tooling/scripts/diag_scheduler.py \
        --db ./data/watchlistarr.db --url http://127.0.0.1:8080

Exit codes: 0 = healthy · 1 = findings printed · 2 = cannot open the DB.
(An unreachable --url only skips the live comparison; the DB is mandatory.)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

EPOCH = datetime(1970, 1, 1)

# Env defaults mirrored from src/watchlistarr/config.py (Settings fields).
# The running app resolves env vars case-insensitively and reads .env too;
# this script does the same (os.environ > --env-file > these defaults).
ENV_DEFAULTS: dict[str, timedelta] = {
    "RSS_INTERVAL": timedelta(minutes=15),
    "WATCHLIST_INCREMENTAL_INTERVAL": timedelta(hours=1),
    "WATCHLIST_FULL_INTERVAL": timedelta(hours=24),
    "LISTS_INCREMENTAL_INTERVAL": timedelta(hours=6),
    "LISTS_FULL_INTERVAL": timedelta(days=7),
    "FILMS_BACKSTOP_INTERVAL": timedelta(hours=24),
    "DISCOVERY_INTERVAL": timedelta(days=7),
    "ROTATION_TICK_INTERVAL": timedelta(hours=1),
}

SCRAPE_RUN_RETENTION = timedelta(days=30)  # scheduler.py:SCRAPE_RUN_RETENTION

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


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


def parse_duration(value: str) -> timedelta | None:
    """Mirror of config.py:_parse_duration for '<int><s|m|h|d>' or raw seconds."""
    value = value.strip().strip("'\"")
    if value.isdigit():
        return timedelta(seconds=int(value))
    match = _DURATION_RE.match(value)
    if not match:
        return None
    return timedelta(seconds=int(match.group(1)) * _DURATION_UNITS[match.group(2).lower()])


def load_env_defaults(env_file: str | None) -> dict[str, timedelta]:
    """ENV_DEFAULTS overridden by --env-file entries, then by os.environ
    (same precedence as pydantic-settings in config.py)."""
    effective = dict(ENV_DEFAULTS)
    file_vars: dict[str, str] = {}
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            file_vars[key.strip().upper()] = val.strip()
    for key in effective:
        raw = os.environ.get(key) or os.environ.get(key.lower()) or file_vars.get(key)
        if raw is None:
            continue
        parsed = parse_duration(raw)
        if parsed is None:
            print(f"WARNING: unparseable duration {key}={raw!r} — using default", file=sys.stderr)
            continue
        effective[key] = parsed
    return effective


def fmt_td(td: timedelta | None) -> str:
    if td is None:
        return "-"
    total = int(td.total_seconds())
    if total % 86400 == 0:
        return f"{total // 86400}d"
    if total % 3600 == 0:
        return f"{total // 3600}h"
    if total % 60 == 0:
        return f"{total // 60}m"
    return f"{total}s"


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def section(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 60 - len(title)))


def job_label(job_id: str, users_by_id: dict[int, str]) -> tuple[str, str]:
    """Mirror of routes/api/v1.py:_job_label — (label, detail) as the dashboard
    'upcoming' panel prints them."""
    if job_id == "rotation-tick":
        return ("Custom lists", "Rotation tick")
    if job_id == "prune-scrape-runs":
        return ("Maintenance", "Prune old scrape runs")
    tail = job_id.rsplit("-", 1)[-1]
    if job_id.startswith("rss-"):
        return (f"{users_by_id.get(int(tail), '?')} RSS", "Viewing logs poll")
    if job_id.startswith("discovery-"):
        return (f"{users_by_id.get(int(tail), '?')} discovery", "Refresh public lists")
    if job_id.startswith("films-backstop-"):
        return (f"{users_by_id.get(int(tail), '?')} films", "Backstop /films/ page")
    if job_id.startswith(("watchlist-incr-", "watchlist-full-")):
        kind = "Incremental" if "incr" in job_id else "Full"
        return (f"{users_by_id.get(int(tail), '?')}/watchlist", f"{kind} scrape")
    if job_id.startswith(("list-incr-", "list-full-")):
        kind = "Incremental" if "incr" in job_id else "Full"
        return (f"list #{tail}", f"{kind} scrape")
    return (job_id, "Scheduled job")


def main() -> int:  # noqa: PLR0912, PLR0915 — linear report, deliberately verbose
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="./data/watchlistarr.db", help="path to SQLite DB file")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080",
        help="base URL of the running instance (dashboard probe; failure is non-fatal)",
    )
    parser.add_argument(
        "--env-file",
        default="./.env",
        help="dotenv file with interval overrides, like the app reads (default ./.env)",
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=2.0,
        help="staleness threshold = grace x effective interval (default 2.0)",
    )
    parser.add_argument(
        "--stuck-hours",
        type=float,
        default=2.0,
        help="RUNNING scrape_runs older than this many hours count as stuck (default 2)",
    )
    args = parser.parse_args()

    conn = open_db_ro(args.db)
    env = load_env_defaults(args.env_file)
    findings: list[str] = []
    now = utcnow_naive()

    # ---- expected jobs from DB state (mirror of scheduler.py:sync_jobs) ----
    users = conn.execute(
        "SELECT id, letterboxd_username, rss_interval, discovery_interval, "
        "films_backstop_interval, watchlist_incremental_interval, watchlist_full_interval "
        "FROM users ORDER BY id"
    ).fetchall()
    users_by_id = {u["id"]: u["letterboxd_username"] for u in users}
    watchlists = {
        r["user_id"]: r
        for r in conn.execute(
            "SELECT id, user_id, enabled FROM lists WHERE source_type = 'watchlist'"
        )
    }
    enabled_lists = conn.execute(
        "SELECT id, user_id, slug, lists_incremental_interval, lists_full_interval "
        "FROM lists WHERE source_type = 'list' AND enabled = 1 ORDER BY id"
    ).fetchall()

    # (job_id, scrape_runs source, scrape_runs target_id, effective interval)
    expected: list[tuple[str, str | None, int | None, timedelta | None]] = [
        ("rotation-tick", "rotation", None, env["ROTATION_TICK_INTERVAL"]),
        ("prune-scrape-runs", None, None, timedelta(days=1)),  # unaudited, see note
    ]
    for u in users:
        uid = u["id"]
        expected.append(
            ("rss-%d" % uid, "rss", uid, parse_interval(u["rss_interval"]) or env["RSS_INTERVAL"])
        )
        expected.append(
            (
                "discovery-%d" % uid,
                "discovery",
                uid,
                parse_interval(u["discovery_interval"]) or env["DISCOVERY_INTERVAL"],
            )
        )
        expected.append(
            (
                "films-backstop-%d" % uid,
                "films",
                uid,
                parse_interval(u["films_backstop_interval"]) or env["FILMS_BACKSTOP_INTERVAL"],
            )
        )
        wl = watchlists.get(uid)
        if wl is not None and wl["enabled"]:
            # Audit rows for watchlist jobs are keyed by the WATCHLIST LIST id,
            # not the user id (scheduler.py:_with_watchlist).
            expected.append(
                (
                    "watchlist-incr-%d" % uid,
                    "watchlist",
                    wl["id"],
                    parse_interval(u["watchlist_incremental_interval"])
                    or env["WATCHLIST_INCREMENTAL_INTERVAL"],
                )
            )
            expected.append(
                (
                    "watchlist-full-%d" % uid,
                    "watchlist",
                    wl["id"],
                    parse_interval(u["watchlist_full_interval"]) or env["WATCHLIST_FULL_INTERVAL"],
                )
            )
    for lst in enabled_lists:
        expected.append(
            (
                "list-incr-%d" % lst["id"],
                "list",
                lst["id"],
                parse_interval(lst["lists_incremental_interval"])
                or env["LISTS_INCREMENTAL_INTERVAL"],
            )
        )
        expected.append(
            (
                "list-full-%d" % lst["id"],
                "list",
                lst["id"],
                parse_interval(lst["lists_full_interval"]) or env["LISTS_FULL_INTERVAL"],
            )
        )

    section("[1] Expected jobs (derived from DB, mirrors scheduler.py:sync_jobs)")
    print(f"{len(users)} user(s), {len(enabled_lists)} enabled non-watchlist list(s), "
          f"{sum(1 for w in watchlists.values() if w['enabled'])} enabled watchlist(s)")
    print(f"-> {len(expected)} expected jobs:")
    for job_id, _, _, interval in expected:
        print(f"  {job_id:28s} every {fmt_td(interval)}")
    print("note: watchlist-incr/full jobs exist ONLY while the user's watchlist row is\n"
          "enabled; list-incr/full ONLY for enabled source_type='list' rows. Disabled\n"
          "lists having no job is CORRECT, not a finding.")

    section("[2] Live scheduler view (GET /api/v1/dashboard, best-effort)")
    dashboard: dict | None = None
    probe_url = f"{args.url.rstrip('/')}/api/v1/dashboard"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(probe_url, method="GET"), timeout=5
        ) as resp:
            dashboard = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"live probe skipped ({probe_url}: {exc})")
        print("Cannot compare against the live scheduler. DB-side checks continue.")
    if dashboard is not None:
        upcoming = dashboard.get("upcoming", [])
        stats = dashboard.get("stats", {})
        print(f"stats: {stats}")
        recent_errors = stats.get("recentErrors", 0)
        if recent_errors:
            findings.append(
                f"{recent_errors} scrape error(s) in the last hour (dashboard stats.recentErrors)"
            )
        expected_labels = {job_label(job_id, users_by_id) for job_id, *_ in expected}
        print(f"upcoming ({len(upcoming)} entries — the dashboard caps at the NEXT 5 jobs, "
              "so absence here proves nothing):")
        for entry in upcoming:
            key = (entry.get("label", ""), entry.get("detail", ""))
            ok = key in expected_labels
            print(f"  {'OK      ' if ok else 'ORPHAN? '}{key[0]} — {key[1]} "
                  f"(eta {entry.get('eta')}, nextRunAt {entry.get('nextRunAt')})")
            if not ok:
                findings.append(
                    f"live job '{key[0]} — {key[1]}' matches no expected job — the scheduler "
                    "holds a job for a deleted/disabled entity; POST /admin/scheduler/sync "
                    "rebuilds it (write op — run manually, this script will not)"
                )
        if not upcoming:
            findings.append(
                "dashboard 'upcoming' is EMPTY — the scheduler has no pending jobs at all "
                "(expected at least rotation-tick + prune-scrape-runs); the scheduler likely "
                "failed to start"
            )

    section(f"[3] Stuck scrape_runs (status='running' older than {args.stuck_hours}h)")
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
            f"{len(stuck_old)} scrape_runs stuck in RUNNING >{args.stuck_hours}h — a restart "
            "marks them ERROR (services/scrape/audit.py:fail_interrupted_runs); if the app IS "
            "running, a job is hung"
        )

    section("[4] Lists with last_sync_status = 'error'")
    err_lists = conn.execute(
        "SELECT l.id, l.slug, l.source_type, l.enabled, l.last_synced_at, "
        "u.letterboxd_username FROM lists l JOIN users u ON u.id = l.user_id "
        "WHERE l.last_sync_status = 'error' ORDER BY u.letterboxd_username, l.slug"
    ).fetchall()
    print(f"{len(err_lists)} list(s) in error state")
    for row in err_lists[:20]:
        print(f"  {row['letterboxd_username']}/{row['slug']} (id={row['id']}, "
              f"type={row['source_type']}, enabled={bool(row['enabled'])}, "
              f"last_synced_at={row['last_synced_at']})")
    if err_lists:
        findings.append(
            f"{len(err_lists)} lists have last_sync_status='error' — check the matching "
            "scrape_runs.error text and /api/v1/activity?level=ERROR"
        )

    section(f"[5] Per-job staleness (finding if last run older than {args.grace} x interval)")
    oldest_run = parse_dt(
        conn.execute("SELECT MIN(started_at) FROM scrape_runs").fetchone()[0]
    )
    print(f"oldest scrape_run: {oldest_run} (runs older than "
          f"{SCRAPE_RUN_RETENTION.days}d are pruned — scheduler.py:SCRAPE_RUN_RETENTION)")
    print("caveats: incr and full jobs of the same target share ONE audit stream "
          "(scrape_runs\nrows do not distinguish them), so each pair is checked against the "
          "INCREMENTAL\ncadence only — a broken full sync with a healthy incremental one is "
          "invisible here.\nprune-scrape-runs writes no audit row at all (unmeasurable).")
    for job_id, source, target_id, interval in expected:
        if source is None or interval is None:
            print(f"  {job_id:28s} unaudited — skipped")
            continue
        if job_id.startswith(("watchlist-full-", "list-full-")):
            print(f"  {job_id:28s} shares audit rows with its -incr twin — skipped")
            continue
        if target_id is None:
            row = conn.execute(
                "SELECT started_at, status FROM scrape_runs WHERE source = ? "
                "AND target_id IS NULL ORDER BY started_at DESC LIMIT 1",
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT started_at, status FROM scrape_runs WHERE source = ? "
                "AND target_id = ? ORDER BY started_at DESC LIMIT 1",
                (source, target_id),
            ).fetchone()
        if row is None:
            print(f"  {job_id:28s} NO scrape_runs row (never ran within the "
                  f"{SCRAPE_RUN_RETENTION.days}d retention window)")
            if oldest_run is not None and (now - oldest_run) > interval:
                findings.append(
                    f"{job_id}: no scrape_runs row although the DB has runs older than its "
                    f"{fmt_td(interval)} interval — job never fires; check "
                    "POST /admin/refresh/{job_id} manually and the scheduler logs"
                )
            continue
        last = parse_dt(row["started_at"]) or now
        age = now - last
        stale = age > timedelta(seconds=interval.total_seconds() * args.grace)
        flag = "STALE " if stale else "ok    "
        print(f"  {flag}{job_id:28s} last={row['started_at']} ({fmt_td(age)} ago, "
              f"interval {fmt_td(interval)}, last status={row['status']})")
        if stale:
            findings.append(
                f"{job_id}: last run {fmt_td(age)} ago exceeds {args.grace} x "
                f"{fmt_td(interval)} — job stalled or scheduler not rebuilt; "
                "POST /admin/refresh/" + job_id + " triggers it once"
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
