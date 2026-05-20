from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import SyncStatus
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.lists import parse_list_items, parse_total_pages
from watchlistarr.services.scrape.anti_flap import reconcile_full_scrape
from watchlistarr.services.scrape.film_resolver import resolve_film

logger = structlog.get_logger(__name__)


def _path(username: str, page: int) -> str:
    return f"/{username}/watchlist/" if page == 1 else f"/{username}/watchlist/page/{page}/"


async def _resolve_slugs(
    session: AsyncSession, client: LetterboxdClient, slugs: list[str]
) -> dict[str, Film]:
    resolved: dict[str, Film] = {}
    for slug in slugs:
        film = await resolve_film(session, client, slug)
        if film is not None:
            resolved[slug] = film
    return resolved


async def _upsert_items(
    session: AsyncSession, list_id: int, ordered_slugs: list[str], films_by_slug: dict[str, Film]
) -> set[int]:
    existing_items = list(
        (await session.execute(select(ListItem).where(ListItem.list_id == list_id))).scalars().all()
    )
    existing_by_tmdb = {it.tmdb_id: it for it in existing_items}
    now = utcnow()
    seen: set[int] = set()
    for position, slug in enumerate(ordered_slugs):
        film = films_by_slug.get(slug)
        if film is None:
            continue
        seen.add(film.tmdb_id)
        item = existing_by_tmdb.get(film.tmdb_id)
        if item is None:
            session.add(
                ListItem(
                    list_id=list_id,
                    tmdb_id=film.tmdb_id,
                    position=position,
                    added_at=now,
                    last_seen_at=now,
                )
            )
        else:
            item.position = position
            item.last_seen_at = now
            item.pending_removal_count = 0
    await session.flush()
    return seen


async def sync_watchlist_full(
    session: AsyncSession, client: LetterboxdClient, watchlist: ListModel
) -> None:
    user = await session.get(User, watchlist.user_id)
    if user is None:
        return

    all_slugs: list[str] = []
    page = 1
    total_pages = 1
    while True:
        response = await client.get(_path(user.letterboxd_username, page))
        html = response.text
        all_slugs.extend(item.slug for item in parse_list_items(html))
        if page == 1:
            total_pages = parse_total_pages(html)
        if page >= total_pages:
            break
        page += 1

    films_by_slug = await _resolve_slugs(session, client, all_slugs)
    await _upsert_items(session, watchlist.id, all_slugs, films_by_slug)

    await reconcile_full_scrape(
        session,
        list_id=watchlist.id,
        user_id=watchlist.user_id,
        scraped_films=films_by_slug.values(),
    )

    watchlist.last_synced_at = utcnow()
    watchlist.last_sync_status = SyncStatus.SUCCESS
    await session.flush()
    logger.info(
        "watchlist.full_sync",
        user_id=watchlist.user_id,
        slugs=len(all_slugs),
        resolved=len(films_by_slug),
    )


async def sync_watchlist_incremental(
    session: AsyncSession, client: LetterboxdClient, watchlist: ListModel
) -> None:
    user = await session.get(User, watchlist.user_id)
    if user is None:
        return
    response = await client.get(_path(user.letterboxd_username, 1))
    page_slugs = [item.slug for item in parse_list_items(response.text)]
    films_by_slug = await _resolve_slugs(session, client, page_slugs)
    await _upsert_items(session, watchlist.id, page_slugs, films_by_slug)
    watchlist.last_synced_at = utcnow()
    watchlist.last_sync_status = SyncStatus.SUCCESS
    await session.flush()
    logger.info(
        "watchlist.incremental_sync",
        user_id=watchlist.user_id,
        slugs=len(page_slugs),
    )
