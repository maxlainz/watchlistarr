import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import Settings
from watchlistarr.models.enums import ScrapeSource, SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.audit import with_scrape_audit
from watchlistarr.services.scrape.discovery import discover_lists
from watchlistarr.services.scrape.films_backstop import backstop_films_for_user
from watchlistarr.services.scrape.initial_run import ensure_watchlist_row
from watchlistarr.services.scrape.lists import sync_list_full
from watchlistarr.services.scrape.watchlist import sync_watchlist_full

logger = structlog.get_logger(__name__)

_background_tasks: set[asyncio.Task[None]] = set()


async def _ensure_watchlist_row(factory: async_sessionmaker[AsyncSession], user_id: int) -> None:
    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        await ensure_watchlist_row(session, user)
        await session.commit()


async def _discover_for_user(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    user_id: int,
) -> None:
    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        # Detach the user to safely use it outside the session boundary; we only
        # read scalar attributes (`letterboxd_username`, `id`).
    await discover_lists(factory, client, user)


async def _backstop_for_user(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    user_id: int,
) -> None:
    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
    await backstop_films_for_user(factory, client, user)


async def _collect_lists(
    factory: async_sessionmaker[AsyncSession], user_id: int
) -> list[tuple[int, SourceType]]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(ListModel.id, ListModel.source_type).where(ListModel.user_id == user_id)
            )
        ).all()
    return [(row[0], row[1]) for row in rows]


async def _run_step(
    factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    coro_factory: Callable[[], Awaitable[Any]],
) -> bool:
    """Envuelve ``coro_factory()`` con auditoría. Se pasa un callable lazy para
    que cada intento construya su propia corrutina."""
    try:
        await with_scrape_audit(factory, source, target_id, coro_factory())
        return True
    except Exception as exc:
        logger.exception("initial_run.step_failed", source=source.value, error=str(exc))
        return False


async def _initial_run(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    scheduler: object | None,
) -> None:
    """Initial onboarding: ensure watchlist row, discover public lists, backstop
    /films/, then full-sync every discovered list (watchlist included). Lists
    stay enabled=False — the user picks which ones to serve, but their items
    are ready the moment they toggle one on."""
    client = LetterboxdClient(settings)
    logger.info("initial_run.background.start", user_id=user_id)
    try:
        await _run_step(
            factory,
            ScrapeSource.DISCOVERY,
            user_id,
            lambda: _ensure_watchlist_row(factory, user_id),
        )
        await _run_step(
            factory,
            ScrapeSource.DISCOVERY,
            user_id,
            lambda: _discover_for_user(factory, client, user_id),
        )
        await _run_step(
            factory,
            ScrapeSource.FILMS,
            user_id,
            lambda: _backstop_for_user(factory, client, user_id),
        )

        for list_id, source_type in await _collect_lists(factory, user_id):
            is_wl = source_type is SourceType.WATCHLIST
            source = ScrapeSource.WATCHLIST if is_wl else ScrapeSource.LIST
            sync = sync_watchlist_full if is_wl else sync_list_full

            def _make(
                sync_fn: Callable[
                    [async_sessionmaker[AsyncSession], LetterboxdClient, int],
                    Awaitable[None],
                ] = sync,
                lid: int = list_id,
            ) -> Callable[[], Awaitable[None]]:
                return lambda: sync_fn(factory, client, lid)

            await _run_step(factory, source, list_id, _make())
    finally:
        await client.aclose()
    logger.info("initial_run.background.done", user_id=user_id)

    if scheduler is not None and hasattr(scheduler, "sync_jobs"):
        try:
            await scheduler.sync_jobs()
        except Exception as exc:
            logger.exception("scheduler.sync_failed", error=str(exc))


def schedule_initial_run(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    scheduler: object | None,
) -> asyncio.Task[None]:
    task = asyncio.create_task(_initial_run(factory, settings, user_id, scheduler))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _sync_single_list(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    list_id: int,
) -> None:
    """Full-sync a single list in its own client. Used by the toggle endpoint to
    kick off an immediate scrape without waiting for the scheduler tick. The
    scraper itself manages short DB transactions; we just wrap it in audit."""
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            list_row = await session.get(ListModel, list_id)
            if list_row is None:
                return
            is_wl = list_row.source_type is SourceType.WATCHLIST
        source = ScrapeSource.WATCHLIST if is_wl else ScrapeSource.LIST
        sync = sync_watchlist_full if is_wl else sync_list_full
        try:
            await with_scrape_audit(factory, source, list_id, sync(factory, client, list_id))
        except Exception as exc:
            logger.exception("toggle.immediate_sync_failed", list_id=list_id, error=str(exc))
    finally:
        await client.aclose()


def schedule_list_sync(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    list_id: int,
) -> asyncio.Task[None]:
    task = asyncio.create_task(_sync_single_list(factory, settings, list_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
