from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from watchlistarr.models.enums import ScrapeSource, ScrapeStatus
from watchlistarr.models.scrape_runs import ScrapeRun
from watchlistarr.models.users import User
from watchlistarr.services.scrape.audit import with_scrape_audit


async def test_with_scrape_audit_records_success(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def work() -> int:
        async with factory() as s:
            s.add(User(letterboxd_username="alice"))
            await s.commit()
        return 42

    result = await with_scrape_audit(factory, ScrapeSource.WATCHLIST, target_id=None, coro=work())
    assert result == 42
    async with factory() as s:
        runs = list((await s.execute(select(ScrapeRun))).scalars().all())
        users = list((await s.execute(select(User))).scalars().all())
    assert len(runs) == 1
    assert runs[0].status is ScrapeStatus.SUCCESS
    assert runs[0].error is None
    assert len(users) == 1


async def test_with_scrape_audit_records_error(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def work() -> None:
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        await with_scrape_audit(factory, ScrapeSource.RSS, target_id=1, coro=work())

    async with factory() as s:
        runs = list((await s.execute(select(ScrapeRun))).scalars().all())
    assert len(runs) == 1
    assert runs[0].status is ScrapeStatus.ERROR
    assert "kaboom" in (runs[0].error or "")
