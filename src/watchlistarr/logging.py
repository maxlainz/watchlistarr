from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import Processor


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
