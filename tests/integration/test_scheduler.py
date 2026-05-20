from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from watchlistarr.config import Settings
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.scheduler import JobScheduler


async def _seed_user(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        user = User(letterboxd_username="alice")
        session.add(user)
        await session.flush()
        session.add(
            ListModel(
                user_id=user.id,
                source_type=SourceType.LIST,
                letterboxd_list_id="1",
                slug="favs",
                name="Favs",
                enabled=True,
            )
        )
        session.add(
            ListModel(
                user_id=user.id,
                source_type=SourceType.WATCHLIST,
                slug="watchlist",
                name="WL",
                enabled=True,
            )
        )
        await session.commit()
        return user.id


async def test_sync_jobs_registers_expected_ids(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    user_id = await _seed_user(factory)
    scheduler = JobScheduler(factory, Settings(letterboxd_offline=True))
    await scheduler.sync_jobs()
    job_ids = {j.id for j in scheduler.jobs}
    assert "rotation-tick" in job_ids
    assert f"rss-{user_id}" in job_ids
    assert f"watchlist-incr-{user_id}" in job_ids
    assert f"watchlist-full-{user_id}" in job_ids
    assert f"discovery-{user_id}" in job_ids
    assert f"films-backstop-{user_id}" in job_ids
    # La lista habilitada (no la watchlist) genera list-incr/full por id de la list.
    assert any(jid.startswith("list-incr-") for jid in job_ids)
    assert any(jid.startswith("list-full-") for jid in job_ids)


async def test_reschedule_updates_interval(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _seed_user(factory)
    scheduler = JobScheduler(factory, Settings(letterboxd_offline=True))
    await scheduler.sync_jobs()
    assert await scheduler.reschedule("rotation-tick", 9999) is True
    assert await scheduler.reschedule("nope", 60) is False
