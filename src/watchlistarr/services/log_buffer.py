from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Loggers cuyos records ya fueron capturados estructuradamente por
# `buffer_capture_processor` en el pipeline structlog. El BufferHandler descarta
# estos para evitar doble captura. Cubre todos los módulos del package
# (`watchlistarr.*`) que usan `structlog.get_logger(__name__)`.
_STRUCTLOG_PREFIXES: tuple[str, ...] = ("watchlistarr",)
# Tope conservador para exc_info en buffer (evita líneas de ~MB tras un crash
# repetido). 4096 chars suele cubrir ~50 frames de Python.
_EXC_INFO_LIMIT = 4096


@dataclass(frozen=True)
class LogLine:
    seq: int
    level: str
    message: str
    ts: datetime
    src: str
    event: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    human_message: str = ""
    exc_info: str | None = None


class _LogBuffer:
    def __init__(self, max_lines: int = 2000) -> None:
        self._lines: deque[LogLine] = deque(maxlen=max_lines)
        self._counter = itertools.count(start=1)
        self._lock = threading.Lock()

    def append(self, level: str, message: str, src: str) -> None:
        """Legacy path: usado por BufferHandler para logs no-structlog."""
        with self._lock:
            self._lines.append(
                LogLine(
                    seq=next(self._counter),
                    level=level,
                    message=message,
                    ts=datetime.now(tz=UTC),
                    src=src,
                    event=None,
                    fields={},
                    human_message=message,
                    exc_info=None,
                )
            )

    def append_structured(
        self,
        *,
        level: str,
        event: str | None,
        fields: dict[str, Any],
        human_message: str,
        raw_message: str,
        ts: datetime,
        src: str,
        exc_info: str | None,
    ) -> None:
        if exc_info is not None and len(exc_info) > _EXC_INFO_LIMIT:
            exc_info = exc_info[:_EXC_INFO_LIMIT] + "\n… (truncated)"
        with self._lock:
            self._lines.append(
                LogLine(
                    seq=next(self._counter),
                    level=level,
                    message=raw_message,
                    ts=ts,
                    src=src,
                    event=event,
                    fields=dict(fields),
                    human_message=human_message,
                    exc_info=exc_info,
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


class BufferHandler(logging.Handler):
    """Espeja al buffer logs que NO pasaron por el pipeline structlog.

    Los logs de structlog son capturados estructuradamente por
    `buffer_capture_processor` antes de llegar al stdlib handler. Cuando el
    processor escribe al buffer, marca el `LogRecord` con `_CAPTURED_ATTR=True`;
    aquí lo detectamos y descartamos para no duplicar. Logs de alembic, uvicorn,
    sqlalchemy, etc. siguen entrando por esta vía y se almacenan sin `event`
    ni `fields`.
    """

    def emit(self, record: logging.LogRecord) -> None:
        name = record.name or ""
        if name.startswith(_STRUCTLOG_PREFIXES):
            return
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        src = name.rsplit(".", 1)[-1] or "root"
        # Import local para evitar ciclo (log_messages no depende de log_buffer).
        from watchlistarr.services.log_messages import humanize_external

        _buffer.append_structured(
            level=record.levelname,
            event=None,
            fields={},
            human_message=humanize_external(msg),
            raw_message=msg,
            ts=datetime.now(tz=UTC),
            src=src,
            exc_info=None,
        )


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
