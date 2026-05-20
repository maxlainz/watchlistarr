import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import Settings
from watchlistarr.models.enums import ScrapeSource
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.audit import with_scrape_audit
from watchlistarr.services.scrape.discovery import discover_lists
from watchlistarr.services.scrape.films_backstop import backstop_films_for_user
from watchlistarr.services.scrape.initial_run import ensure_watchlist_row

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


async def _initial_run(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    scheduler: object | None,
) -> None:
    """Initial onboarding: discover lists + films-backstop. Nothing is enabled
    until the user toggles it on; the watchlist is NOT scraped automatically."""
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
