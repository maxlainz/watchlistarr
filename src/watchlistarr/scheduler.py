from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import Settings
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services import intervals
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.rotation import rotation_tick
from watchlistarr.services.scrape.discovery import discover_lists
from watchlistarr.services.scrape.films_backstop import backstop_films_for_user
from watchlistarr.services.scrape.lists import sync_list_full, sync_list_incremental
from watchlistarr.services.scrape.rss_watcher import poll_rss_for_user
from watchlistarr.services.scrape.watchlist import (
    sync_watchlist_full,
    sync_watchlist_incremental,
)

logger = structlog.get_logger(__name__)


def _seconds(td: timedelta) -> int:
    return max(1, int(td.total_seconds()))


class JobScheduler:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.start()

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=True)

    @property
    def jobs(self) -> list[Any]:
        return list(self._scheduler.get_jobs())

    async def trigger_now(self, job_id: str) -> bool:
        job = self._scheduler.get_job(job_id)
        if job is None:
            return False
        await job.func(*job.args, **job.kwargs)
        return True

    async def reschedule(self, job_id: str, seconds: int) -> bool:
        job = self._scheduler.get_job(job_id)
        if job is None:
            return False
        self._scheduler.reschedule_job(job_id, trigger=IntervalTrigger(seconds=seconds))
        return True

    async def sync_jobs(self) -> None:
        async with self._factory() as session:
            users = list((await session.execute(select(User))).scalars().all())
            lists_by_user = await _enabled_lists_by_user(session, [u.id for u in users])

        self._scheduler.remove_all_jobs()

        env = self._settings
        self._add(
            "rotation-tick",
            _run_rotation_tick,
            _seconds(env.rotation_tick_interval),
            self._factory,
        )

        for user in users:
            uid = user.id
            self._add(
                f"rss-{uid}",
                _run_rss,
                _seconds(intervals.user_rss_interval(user, env)),
                self._factory,
                env,
                uid,
            )
            self._add(
                f"watchlist-incr-{uid}",
                _run_watchlist_incremental,
                _seconds(intervals.user_watchlist_incremental(user, env)),
                self._factory,
                env,
                uid,
            )
            self._add(
                f"watchlist-full-{uid}",
                _run_watchlist_full,
                _seconds(intervals.user_watchlist_full(user, env)),
                self._factory,
                env,
                uid,
            )
            self._add(
                f"discovery-{uid}",
                _run_discovery,
                _seconds(intervals.user_discovery(user, env)),
                self._factory,
                env,
                uid,
            )
            self._add(
                f"films-backstop-{uid}",
                _run_films_backstop,
                _seconds(intervals.user_films_backstop(user, env)),
                self._factory,
                env,
                uid,
            )
            for lst in lists_by_user.get(uid, []):
                self._add(
                    f"list-incr-{lst.id}",
                    _run_list_incremental,
                    _seconds(intervals.list_incremental(lst, env)),
                    self._factory,
                    env,
                    lst.id,
                )
                self._add(
                    f"list-full-{lst.id}",
                    _run_list_full,
                    _seconds(intervals.list_full(lst, env)),
                    self._factory,
                    env,
                    lst.id,
                )

        logger.info("scheduler.synced", jobs=len(self._scheduler.get_jobs()))

    def _add(
        self,
        job_id: str,
        func: Callable[..., Awaitable[Any]],
        seconds: int,
        *args: Any,
    ) -> None:
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds),
            args=list(args),
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )


async def _enabled_lists_by_user(
    session: AsyncSession, user_ids: list[int]
) -> dict[int, list[ListModel]]:
    if not user_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id.in_(user_ids),
                    ListModel.source_type == SourceType.LIST,
                    ListModel.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    result: dict[int, list[ListModel]] = {}
    for lst in rows:
        result.setdefault(lst.user_id, []).append(lst)
    return result


async def _with_user(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    body: Callable[[AsyncSession, LetterboxdClient, User], Awaitable[Any]],
) -> None:
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            await body(session, client, user)
            await session.commit()
    finally:
        await client.aclose()


async def _with_list(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    list_id: int,
    body: Callable[[AsyncSession, LetterboxdClient, ListModel], Awaitable[None]],
) -> None:
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            list_row = await session.get(ListModel, list_id)
            if list_row is None:
                return
            await body(session, client, list_row)
            await session.commit()
    finally:
        await client.aclose()


async def _run_rss(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_user(factory, settings, user_id, poll_rss_for_user)


async def _run_watchlist_incremental(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    async def body(session: AsyncSession, client: LetterboxdClient, user: User) -> None:
        watchlist = (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id == user.id,
                    ListModel.source_type == SourceType.WATCHLIST,
                )
            )
        ).scalar_one_or_none()
        if watchlist is None:
            return
        await sync_watchlist_incremental(session, client, watchlist)

    await _with_user(factory, settings, user_id, body)


async def _run_watchlist_full(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    async def body(session: AsyncSession, client: LetterboxdClient, user: User) -> None:
        watchlist = (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id == user.id,
                    ListModel.source_type == SourceType.WATCHLIST,
                )
            )
        ).scalar_one_or_none()
        if watchlist is None:
            return
        await sync_watchlist_full(session, client, watchlist)

    await _with_user(factory, settings, user_id, body)


async def _run_discovery(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    async def body(session: AsyncSession, client: LetterboxdClient, user: User) -> None:
        await discover_lists(session, client, user)

    await _with_user(factory, settings, user_id, body)


async def _run_films_backstop(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_user(factory, settings, user_id, backstop_films_for_user)


async def _run_list_incremental(
    factory: async_sessionmaker[AsyncSession], settings: Settings, list_id: int
) -> None:
    await _with_list(factory, settings, list_id, sync_list_incremental)


async def _run_list_full(
    factory: async_sessionmaker[AsyncSession], settings: Settings, list_id: int
) -> None:
    await _with_list(factory, settings, list_id, sync_list_full)


async def _run_rotation_tick(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await rotation_tick(session)
        await session.commit()
