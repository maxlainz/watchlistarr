from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from watchlistarr.services.log_buffer import get_buffer
from watchlistarr.services.log_messages import humanize

# Keys propias de structlog que no son fields de negocio.
_INTERNAL_KEYS = frozenset(
    {"event", "level", "timestamp", "logger", "exception", "stack_info", "exc_info"}
)

# Renderer dedicado a producir la representación plain del log para el campo
# `raw_message` del buffer. Sin colores ANSI (la UI los mostraría como basura).
_RAW_RENDERER = structlog.dev.ConsoleRenderer(colors=False)


def _coerce_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def buffer_capture_processor(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Captura el evento estructurado en el buffer antes del renderer final.

    Corre como penúltimo paso del pipeline structlog: el dict ya tiene level,
    timestamp y `exception` formateada (porque `format_exc_info` ya pasó). El
    dict se devuelve intacto para que el renderer aguas abajo lo emita a stdout
    como hoy.
    """
    event_name = str(event_dict.get("event") or "") or None
    level = str(event_dict.get("level") or method_name or "info").upper()
    ts = _coerce_ts(event_dict.get("timestamp"))
    exc_info = event_dict.get("exception")
    if exc_info is not None and not isinstance(exc_info, str):
        exc_info = str(exc_info)

    fields: dict[str, Any] = {k: v for k, v in event_dict.items() if k not in _INTERNAL_KEYS}

    src = event_name.split(".", 1)[0] if event_name else "structlog"

    # Renderiza el dict completo a string plain (igual que stdout pero sin ANSI).
    # Pasamos una copia para que el renderer no mute el dict original.
    raw_message = _RAW_RENDERER(logger, method_name, dict(event_dict))
    if not isinstance(raw_message, str):
        raw_message = str(raw_message)

    human = humanize(event_name, fields, raw_message)

    get_buffer().append_structured(
        level=level,
        event=event_name,
        fields=fields,
        human_message=human,
        raw_message=raw_message,
        ts=ts,
        src=src,
        exc_info=exc_info if isinstance(exc_info, str) else None,
    )
    return event_dict


def setup_logging(level: str = "info", fmt: str = "plain") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    # force=True para sobrescribir handlers que alembic.fileConfig pudo dejar
    # (que apuntan a stderr con level WARN y filtrarían nuestros INFO de structlog).
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level, force=True)
    logging.getLogger().setLevel(log_level)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        buffer_capture_processor,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
