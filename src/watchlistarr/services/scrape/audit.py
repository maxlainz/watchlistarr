from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.enums import ScrapeSource, ScrapeStatus
from watchlistarr.models.scrape_runs import ScrapeRun

logger = structlog.get_logger(__name__)


async def fail_interrupted_runs(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Marca como error los runs que quedaron en RUNNING tras un crash/restart.

    Sin esto, la UI muestra spinners perpetuos y el toggle de lista nunca
    relanza el sync inmediato (cree que hay un run en vuelo)."""
    async with session_factory() as session:
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(ScrapeRun)
                .where(ScrapeRun.status == ScrapeStatus.RUNNING)
                .values(
                    status=ScrapeStatus.ERROR,
                    ended_at=datetime.now(UTC),
                    error="interrupted by restart",
                )
            ),
        )
        await session.commit()
    if result.rowcount:
        logger.warning("scrape_runs.interrupted_cleaned", count=result.rowcount)


async def with_scrape_audit[T](
    session_factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    coro: Awaitable[T],
) -> T:
    """Envuelve una corrutina con un ``ScrapeRun`` de auditoría.

    A diferencia de la versión anterior, NO inyecta una sesión: los scrapers
    son responsables de abrir y cerrar sus propias sesiones (con transacciones
    cortas) para no bloquear el write-lock de SQLite mientras hacen HTTP.
    """
    started = datetime.now(UTC)
    run_id = await _start(session_factory, source, target_id, started)
    try:
        result = await coro
        ended = datetime.now(UTC)
        await _finish(session_factory, run_id, ended, ScrapeStatus.SUCCESS, None)
        return result
    except Exception as exc:
        ended = datetime.now(UTC)
        await _finish(session_factory, run_id, ended, ScrapeStatus.ERROR, str(exc)[:2000])
        raise


async def _start(
    session_factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    started: datetime,
) -> int:
    async with session_factory() as audit:
        run = ScrapeRun(
            source=source,
            target_id=target_id,
            started_at=started,
            status=ScrapeStatus.RUNNING,
        )
        audit.add(run)
        await audit.commit()
        await audit.refresh(run)
        return run.id


async def _finish(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: int,
    ended: datetime,
    status: ScrapeStatus,
    error: str | None,
) -> None:
    async with session_factory() as audit:
        run = await audit.get(ScrapeRun, run_id)
        if run is None:
            return
        run.status = status
        run.ended_at = ended
        run.error = error
        await audit.commit()
