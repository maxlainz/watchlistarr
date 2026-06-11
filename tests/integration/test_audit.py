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


async def test_fail_interrupted_runs_marks_running_as_error(engine: AsyncEngine) -> None:
    from watchlistarr.services.scrape.audit import fail_interrupted_runs

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        s.add(ScrapeRun(source=ScrapeSource.LIST, target_id=1, status=ScrapeStatus.RUNNING))
        s.add(ScrapeRun(source=ScrapeSource.RSS, target_id=2, status=ScrapeStatus.SUCCESS))
        await s.commit()

    await fail_interrupted_runs(factory)

    async with factory() as s:
        runs = {r.target_id: r for r in (await s.execute(select(ScrapeRun))).scalars().all()}
    assert runs[1].status is ScrapeStatus.ERROR
    assert runs[1].error == "interrupted by restart"
    assert runs[1].ended_at is not None
    assert runs[2].status is ScrapeStatus.SUCCESS


async def test_failed_list_runner_audits_and_marks_sync_error(engine: AsyncEngine) -> None:
    from watchlistarr.config import Settings
    from watchlistarr.models.enums import SourceType, SyncStatus
    from watchlistarr.models.lists import List as ListModel
    from watchlistarr.scheduler import _run_list_full

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        user = User(letterboxd_username="alice")
        s.add(user)
        await s.flush()
        lst = ListModel(
            user_id=user.id,
            source_type=SourceType.LIST,
            letterboxd_list_id="1",
            slug="favs",
            name="Favs",
            enabled=True,
            last_sync_status=SyncStatus.SUCCESS,
        )
        s.add(lst)
        await s.commit()
        list_id = lst.id

    # letterboxd_offline=True hace que el primer GET lance LetterboxdOfflineError.
    with pytest.raises(Exception, match="LETTERBOXD_OFFLINE"):
        await _run_list_full(factory, Settings(letterboxd_offline=True), list_id)

    async with factory() as s:
        run = (await s.execute(select(ScrapeRun))).scalars().one()
        assert run.status is ScrapeStatus.ERROR
        assert run.source is ScrapeSource.LIST
        assert run.target_id == list_id
        refreshed = await s.get(ListModel, list_id)
        assert refreshed is not None
        assert refreshed.last_sync_status is SyncStatus.ERROR
