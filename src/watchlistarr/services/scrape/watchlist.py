from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import get_settings
from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import SyncStatus
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services import intervals
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.lists import parse_list_items, parse_total_pages
from watchlistarr.services.scrape.anti_flap import adhoc_films_backstop, reconcile_full_scrape
from watchlistarr.services.scrape.film_resolver import ResolvedFilm, resolve_films

logger = structlog.get_logger(__name__)


def _path(username: str, page: int) -> str:
    return f"/{username}/watchlist/" if page == 1 else f"/{username}/watchlist/page/{page}/"


async def _upsert_items(
    session: AsyncSession,
    list_id: int,
    ordered_slugs: list[str],
    films_by_slug: dict[str, ResolvedFilm],
    *,
    reassign_positions: bool = True,
) -> set[int]:
    """Upsert de ``list_items`` por slug.

    ``reassign_positions`` controla si la position de items existentes se
    reescribe con su índice en ``ordered_slugs``. En scrapes completos sí; en
    incrementales no — el slice escrapeado (página 1 + última página) no
    refleja la position real en la lista y reescribirla corrompe el orden
    enviado a Radarr hasta el siguiente full sync.
    """
    existing_items = list(
        (await session.execute(select(ListItem).where(ListItem.list_id == list_id))).scalars().all()
    )
    existing_by_tmdb = {it.tmdb_id: it for it in existing_items}
    now = utcnow()
    seen: set[int] = set()
    next_new_position = max((it.position for it in existing_items), default=-1) + 1
    for position, slug in enumerate(ordered_slugs):
        film = films_by_slug.get(slug)
        if film is None:
            continue
        if film.tmdb_id in seen:
            continue
        seen.add(film.tmdb_id)
        item = existing_by_tmdb.get(film.tmdb_id)
        if item is None:
            if reassign_positions:
                insert_position = position
            else:
                insert_position = next_new_position
                next_new_position += 1
            session.add(
                ListItem(
                    list_id=list_id,
                    tmdb_id=film.tmdb_id,
                    position=insert_position,
                    added_at=now,
                    last_seen_at=now,
                )
            )
        else:
            if reassign_positions:
                item.position = position
            item.last_seen_at = now
            item.pending_removal_count = 0
    return seen


async def _fetch_username(
    factory: async_sessionmaker[AsyncSession], list_id: int
) -> tuple[str, int] | None:
    """Devuelve (username, user_id) del owner del list_id, o None si no existe."""
    async with factory() as session:
        list_row = await session.get(ListModel, list_id)
        if list_row is None:
            return None
        user = await session.get(User, list_row.user_id)
        if user is None:
            return None
        return user.letterboxd_username, user.id


async def _fetch_all_pages(client: LetterboxdClient, username: str) -> list[str]:
    all_slugs: list[str] = []
    page = 1
    total_pages = 1
    while True:
        response = await client.get(_path(username, page))
        html = response.text
        page_slugs = [item.slug for item in parse_list_items(html)]
        all_slugs.extend(page_slugs)
        if page == 1:
            total_pages = parse_total_pages(html)
        logger.info(
            "watchlist.full_sync.page",
            username=username,
            page=page,
            total_pages=total_pages,
            page_items=len(page_slugs),
        )
        if page >= total_pages:
            break
        page += 1
    return all_slugs


async def sync_watchlist_full(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    list_id: int,
) -> None:
    owner = await _fetch_username(factory, list_id)
    if owner is None:
        return
    username, user_id = owner

    logger.info(
        "watchlist.full_sync.start",
        user_id=user_id,
        username=username,
        list_id=list_id,
    )
    all_slugs = await _fetch_all_pages(client, username)

    logger.info(
        "watchlist.full_sync.resolving",
        user_id=user_id,
        username=username,
        list_id=list_id,
        total_slugs=len(all_slugs),
    )
    resolved = await resolve_films(factory, client, all_slugs)
    films_page_tmdb_ids = await adhoc_films_backstop(
        factory,
        client,
        username=username,
        list_id=list_id,
        user_id=user_id,
        scraped_tmdb_ids={f.tmdb_id for f in resolved.values()},
    )

    async with factory() as session:
        watchlist = await session.get(ListModel, list_id)
        if watchlist is None:
            return
        await _upsert_items(session, list_id, all_slugs, resolved)
        await reconcile_full_scrape(
            session,
            list_id=list_id,
            user_id=user_id,
            scraped_films=resolved.values(),
            threshold=intervals.list_flap_threshold(watchlist, get_settings()),
            films_page_tmdb_ids=films_page_tmdb_ids,
        )
        watchlist.last_synced_at = utcnow()
        watchlist.last_sync_status = SyncStatus.SUCCESS
        await session.commit()

    logger.info(
        "watchlist.full_sync",
        user_id=user_id,
        username=username,
        list_id=list_id,
        slugs=len(all_slugs),
        resolved=len(resolved),
    )


async def sync_watchlist_incremental(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    list_id: int,
) -> None:
    owner = await _fetch_username(factory, list_id)
    if owner is None:
        return
    username, user_id = owner

    response = await client.get(_path(username, 1))
    page_slugs = [item.slug for item in parse_list_items(response.text)]
    resolved = await resolve_films(factory, client, page_slugs)

    async with factory() as session:
        watchlist = await session.get(ListModel, list_id)
        if watchlist is None:
            return
        await _upsert_items(session, list_id, page_slugs, resolved, reassign_positions=False)
        watchlist.last_synced_at = utcnow()
        watchlist.last_sync_status = SyncStatus.SUCCESS
        await session.commit()

    logger.info(
        "watchlist.incremental_sync",
        user_id=user_id,
        username=username,
        list_id=list_id,
        slugs=len(page_slugs),
    )
