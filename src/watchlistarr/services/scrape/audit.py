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
    try:
        async with session_factory() as work:
            result = await body(work)
            await work.commit()
        ended = datetime.now(UTC)
        await _record(
            session_factory, source, target_id, started, ended, ScrapeStatus.SUCCESS, None
        )
        return result
    except Exception as exc:
        ended = datetime.now(UTC)
        await _record(
            session_factory, source, target_id, started, ended, ScrapeStatus.ERROR, str(exc)[:2000]
        )
        raise


async def _record(
    session_factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    started: datetime,
    ended: datetime,
    status: ScrapeStatus,
    error: str | None,
) -> None:
    async with session_factory() as audit:
        audit.add(
            ScrapeRun(
                source=source,
                target_id=target_id,
                started_at=started,
                ended_at=ended,
                status=status,
                error=error,
            )
        )
        await audit.commit()
