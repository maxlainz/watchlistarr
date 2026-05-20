import asyncio
from collections.abc import Awaitable, Callable

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


async def _run_step(
    factory: async_sessionmaker[AsyncSession],
    source: ScrapeSource,
    target_id: int | None,
    body: Callable[[AsyncSession], Awaitable[None]],
) -> bool:
    try:
        await with_scrape_audit(factory, source, target_id, body)
        return True
    except Exception as exc:
        logger.exception("initial_run.step_failed", source=source.value, error=str(exc))
        return False


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

        async def _ensure_wl(session: AsyncSession) -> None:
            user = await session.get(User, user_id)
            if user is None:
                return
            await ensure_watchlist_row(session, user)

        async def _discover(session: AsyncSession) -> None:
            user = await session.get(User, user_id)
            if user is None:
                return
            await discover_lists(session, client, user)

        async def _backstop(session: AsyncSession) -> None:
            user = await session.get(User, user_id)
            if user is None:
                return
            await backstop_films_for_user(session, client, user)

        await _run_step(factory, ScrapeSource.DISCOVERY, user_id, _ensure_wl)
        await _run_step(factory, ScrapeSource.DISCOVERY, user_id, _discover)
        await _run_step(factory, ScrapeSource.FILMS, user_id, _backstop)

        # Sequential full sync of every discovered list so items are ready when
        # the user enables one. Sequential (not parallel) to avoid bursts against
        # Letterboxd; each list will take 30s-5m depending on film count.
        for list_id, source_type in await _collect_lists(factory, user_id):
            is_wl = source_type is SourceType.WATCHLIST
            source = ScrapeSource.WATCHLIST if is_wl else ScrapeSource.LIST

            async def _sync_one(
                session: AsyncSession, _list_id: int = list_id, _is_wl: bool = is_wl
            ) -> None:
                list_row = await session.get(ListModel, _list_id)
                if list_row is None:
                    return
                if _is_wl:
                    await sync_watchlist_full(session, client, list_row)
                else:
                    await sync_list_full(session, client, list_row)

            await _run_step(factory, source, list_id, _sync_one)
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
    """Full-sync a single list in its own session + client. Used by the toggle
    endpoint to kick off an immediate scrape without waiting for the scheduler
    tick. Audited like any other scrape."""
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            list_row = await session.get(ListModel, list_id)
            if list_row is None:
                return
            is_wl = list_row.source_type is SourceType.WATCHLIST
        source = ScrapeSource.WATCHLIST if is_wl else ScrapeSource.LIST

        async def _body(session: AsyncSession) -> None:
            list_row = await session.get(ListModel, list_id)
            if list_row is None:
                return
            if list_row.source_type is SourceType.WATCHLIST:
                await sync_watchlist_full(session, client, list_row)
            else:
                await sync_list_full(session, client, list_row)

        try:
            await with_scrape_audit(factory, source, list_id, _body)
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
