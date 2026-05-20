from __future__ import annotations

import itertools
import logging
import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class LogLine:
    seq: int
    level: str
    message: str
    ts: datetime
    src: str


class _LogBuffer:
    def __init__(self, max_lines: int = 2000) -> None:
        self._lines: deque[LogLine] = deque(maxlen=max_lines)
        self._counter = itertools.count(start=1)
        self._lock = threading.Lock()

    def append(self, level: str, message: str, src: str) -> None:
        with self._lock:
            self._lines.append(
                LogLine(
                    seq=next(self._counter),
                    level=level,
                    message=message,
                    ts=datetime.now(tz=UTC),
                    src=src,
                )
            )

    def snapshot(self, since: int = 0, limit: int | None = None) -> list[LogLine]:
        with self._lock:
            lines = [line for line in self._lines if line.seq > since]
        if limit is not None and len(lines) > limit:
            lines = lines[-limit:]
        return lines

    def latest_seq(self) -> int:
        with self._lock:
            if not self._lines:
                return 0
            return self._lines[-1].seq

    def dump_text(self) -> str:
        with self._lock:
            return "\n".join(
                f"{line.ts.isoformat()} {line.level:<5} [{line.src}] {line.message}"
                for line in self._lines
            )


_buffer = _LogBuffer()


def get_buffer() -> _LogBuffer:
    return _buffer


# structlog renderer emits "key=value" pairs; the event key carries the dotted
# source (e.g. "letterboxd.client"). Pull it out so the activity tail can
# colour-group lines by component without re-running the structlog processors.
_EVENT_RE = re.compile(r"\bevent=(?:'([^']*)'|\"([^\"]*)\"|(\S+))")


def _extract_src(record: logging.LogRecord, fallback_msg: str) -> str:
    match = _EVENT_RE.search(fallback_msg)
    if match is not None:
        event = next((g for g in match.groups() if g), None)
        if event:
            return event.split(".", 1)[0]
    name = record.name or "root"
    return name.rsplit(".", 1)[-1]


class BufferHandler(logging.Handler):
    """Logging handler that mirrors log records into the in-memory buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        src = _extract_src(record, msg)
        _buffer.append(record.levelname, msg, src)


def install_buffer_handler() -> BufferHandler:
    """Attach the buffer handler to the root logger if not already attached."""
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, BufferHandler):
            return handler
    handler = BufferHandler(level=logging.NOTSET)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    return handler
