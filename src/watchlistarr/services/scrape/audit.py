from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.enums import ScrapeSource, ScrapeStatus
from watchlistarr.models.scrape_runs import ScrapeRun


async def with_scrape_audit[T](
    session_factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    body: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    started = datetime.now(UTC)
    # Record the run as RUNNING up-front so callers can detect in-flight scrapes.
    run_id = await _start(session_factory, source, target_id, started)
    try:
        async with session_factory() as work:
            result = await body(work)
            await work.commit()
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
