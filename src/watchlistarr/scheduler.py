from __future__ import annotations

import asyncio
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
from watchlistarr.services.custom_lists import rotation_tick
from watchlistarr.services.letterboxd.client import LetterboxdClient
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
        # ``AsyncIOScheduler.shutdown(wait=True)`` es síncrono y bloquea el
        # event loop esperando jobs en vuelo. En el lifespan de FastAPI esto
        # retrasa el cierre limpio — delegamos al threadpool.
        await asyncio.to_thread(self._scheduler.shutdown, True)

    @property
    def jobs(self) -> list[Any]:
        return list(self._scheduler.get_jobs())

    def upcoming_jobs(self, limit: int = 5) -> list[dict[str, Any]]:
        jobs = [j for j in self._scheduler.get_jobs() if j.next_run_time is not None]
        jobs.sort(key=lambda j: j.next_run_time)
        return [{"id": j.id, "next_run_time": j.next_run_time} for j in jobs[:limit]]

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
            watchlist_enabled = await _watchlist_enabled_by_user(session, [u.id for u in users])

        self._scheduler.remove_all_jobs()

        env = self._settings
        self._add(
            "rotation-tick",
            _run_rotation_tick,
            _seconds(env.rotation_tick_interval),
            self._factory,
            name="Custom list rotation tick",
        )

        for user in users:
            uid = user.id
            username = user.letterboxd_username
            self._add(
                f"rss-{uid}",
                _run_rss,
                _seconds(intervals.user_rss_interval(user, env)),
                self._factory,
                env,
                uid,
                name=f"RSS poll · {username}",
            )
            self._add(
                f"discovery-{uid}",
                _run_discovery,
                _seconds(intervals.user_discovery(user, env)),
                self._factory,
                env,
                uid,
                name=f"List discovery · {username}",
            )
            self._add(
                f"films-backstop-{uid}",
                _run_films_backstop,
                _seconds(intervals.user_films_backstop(user, env)),
                self._factory,
                env,
                uid,
                name=f"Films backstop · {username}",
            )
            if watchlist_enabled.get(uid, False):
                self._add(
                    f"watchlist-incr-{uid}",
                    _run_watchlist_incremental,
                    _seconds(intervals.user_watchlist_incremental(user, env)),
                    self._factory,
                    env,
                    uid,
                    name=f"Watchlist incremental sync · {username}",
                )
                self._add(
                    f"watchlist-full-{uid}",
                    _run_watchlist_full,
                    _seconds(intervals.user_watchlist_full(user, env)),
                    self._factory,
                    env,
                    uid,
                    name=f"Watchlist full sync · {username}",
                )
            for lst in lists_by_user.get(uid, []):
                self._add(
                    f"list-incr-{lst.id}",
                    _run_list_incremental,
                    _seconds(intervals.list_incremental(lst, env)),
                    self._factory,
                    env,
                    lst.id,
                    name=f"List incremental sync · {username}/{lst.slug}",
                )
                self._add(
                    f"list-full-{lst.id}",
                    _run_list_full,
                    _seconds(intervals.list_full(lst, env)),
                    self._factory,
                    env,
                    lst.id,
                    name=f"List full sync · {username}/{lst.slug}",
                )

        logger.info("scheduler.synced", jobs=len(self._scheduler.get_jobs()))

    def _add(
        self,
        job_id: str,
        func: Callable[..., Awaitable[Any]],
        seconds: int,
        *args: Any,
        name: str,
    ) -> None:
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=seconds),
            args=list(args),
            id=job_id,
            name=name,
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


async def _watchlist_enabled_by_user(session: AsyncSession, user_ids: list[int]) -> dict[int, bool]:
    if not user_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id.in_(user_ids),
                    ListModel.source_type == SourceType.WATCHLIST,
                    ListModel.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return {lst.user_id: True for lst in rows}


async def _with_user(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    body: Callable[[async_sessionmaker[AsyncSession], LetterboxdClient, User], Awaitable[Any]],
) -> None:
    """Lookup del user en sesión corta y delega al body. El body abre sus propias
    sesiones de escritura para no mantener el write-lock durante HTTP."""
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
        await body(factory, client, user)
    finally:
        await client.aclose()


async def _with_watchlist(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    body: Callable[[async_sessionmaker[AsyncSession], LetterboxdClient, int], Awaitable[Any]],
    *,
    kind: str,
) -> None:
    """Resuelve la watchlist del user en sesión corta y delega al body con su list_id.

    Respeta el cooldown ``user.watchlist_min_sync_interval`` — si el último sync
    fue hace menos tiempo que el cooldown, skip silenciosamente.
    """
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            row = (
                await session.execute(
                    select(ListModel).where(
                        ListModel.user_id == user_id,
                        ListModel.source_type == SourceType.WATCHLIST,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return
            if intervals.watchlist_in_cooldown(user, row):
                logger.info(
                    "scheduler.cooldown_skip",
                    user_id=user_id,
                    kind=f"watchlist_{kind}",
                )
                return
            list_id = row.id
        await body(factory, client, list_id)
    finally:
        await client.aclose()


async def _run_rss(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_user(factory, settings, user_id, poll_rss_for_user)


async def _run_watchlist_incremental(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_watchlist(
        factory, settings, user_id, sync_watchlist_incremental, kind="incremental"
    )


async def _run_watchlist_full(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_watchlist(factory, settings, user_id, sync_watchlist_full, kind="full")


async def _run_discovery(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_user(factory, settings, user_id, discover_lists)


async def _run_films_backstop(
    factory: async_sessionmaker[AsyncSession], settings: Settings, user_id: int
) -> None:
    await _with_user(factory, settings, user_id, backstop_films_for_user)


async def _list_cooldown_skip(
    factory: async_sessionmaker[AsyncSession], list_id: int, kind: str
) -> bool:
    async with factory() as session:
        lst = await session.get(ListModel, list_id)
        if lst is None:
            return True
        if intervals.list_in_cooldown(lst):
            logger.info("scheduler.cooldown_skip", list_id=list_id, kind=f"list_{kind}")
            return True
    return False


async def _run_list_incremental(
    factory: async_sessionmaker[AsyncSession], settings: Settings, list_id: int
) -> None:
    if await _list_cooldown_skip(factory, list_id, "incremental"):
        return
    client = LetterboxdClient(settings)
    try:
        await sync_list_incremental(factory, client, list_id)
    finally:
        await client.aclose()


async def _run_list_full(
    factory: async_sessionmaker[AsyncSession], settings: Settings, list_id: int
) -> None:
    if await _list_cooldown_skip(factory, list_id, "full"):
        return
    client = LetterboxdClient(settings)
    try:
        await sync_list_full(factory, client, list_id)
    finally:
        await client.aclose()


async def _run_rotation_tick(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await rotation_tick(session)
        await session.commit()
