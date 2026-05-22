from __future__ import annotations

import logging
from datetime import UTC, datetime

from watchlistarr.services.log_buffer import (
    BufferHandler,
    _LogBuffer,
)


def _record(name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_append_structured_preserves_event_and_fields() -> None:
    buf = _LogBuffer(max_lines=10)
    ts = datetime(2026, 5, 22, 14, 30, 15, tzinfo=UTC)
    buf.append_structured(
        level="INFO",
        event="watchlist.full_sync.start",
        fields={"user_id": 7, "list_id": 42},
        human_message="Watchlist full sync starting (user 7, list 42)",
        raw_message="2026-05-22 [info] watchlist.full_sync.start user_id=7 list_id=42",
        ts=ts,
        src="watchlist",
        exc_info=None,
    )
    [line] = buf.snapshot()
    assert line.event == "watchlist.full_sync.start"
    assert line.fields == {"user_id": 7, "list_id": 42}
    assert line.human_message.startswith("Watchlist full sync starting")
    assert line.level == "INFO"
    assert line.src == "watchlist"
    assert line.exc_info is None


def test_append_structured_truncates_long_exc_info() -> None:
    buf = _LogBuffer(max_lines=10)
    huge = "x" * 10_000
    buf.append_structured(
        level="ERROR",
        event="request.unhandled_exception",
        fields={},
        human_message="boom",
        raw_message="boom",
        ts=datetime.now(tz=UTC),
        src="request",
        exc_info=huge,
    )
    [line] = buf.snapshot()
    assert line.exc_info is not None
    assert len(line.exc_info) < len(huge)
    assert line.exc_info.endswith("… (truncated)")


def test_legacy_append_keeps_back_compat_fields() -> None:
    buf = _LogBuffer(max_lines=10)
    buf.append("INFO", "alembic message", "migration")
    [line] = buf.snapshot()
    assert line.event is None
    assert line.fields == {}
    assert line.human_message == "alembic message"
    assert line.message == "alembic message"
    assert line.src == "migration"


def test_buffer_handler_skips_structlog_records(monkeypatch) -> None:
    """Records de loggers `watchlistarr.*` se asume que ya pasaron por el
    structlog processor — el handler debe descartarlos para no duplicar."""
    captured: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "watchlistarr.services.log_buffer._buffer",
        type(
            "Fake",
            (),
            {"append": lambda self, level, msg, src: captured.append((level, msg, src))},
        )(),
    )
    handler = BufferHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record("watchlistarr.scrape.watchlist", logging.INFO, "structlog log"))
    handler.emit(_record("alembic.runtime", logging.INFO, "alembic log"))
    assert captured == [("INFO", "alembic log", "runtime")]


def test_snapshot_since_returns_only_newer() -> None:
    buf = _LogBuffer(max_lines=10)
    for i in range(5):
        buf.append("INFO", f"msg-{i}", "test")
    # counter empieza en 1, así que tras 5 appends los seqs son 1..5.
    after = buf.snapshot(since=3)
    assert [line.message for line in after] == ["msg-3", "msg-4"]


def test_latest_seq_increments() -> None:
    buf = _LogBuffer(max_lines=10)
    assert buf.latest_seq() == 0
    buf.append("INFO", "x", "test")
    assert buf.latest_seq() == 1
    buf.append("INFO", "y", "test")
    assert buf.latest_seq() == 2
