from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import get_settings
from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import SyncStatus
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services import intervals
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.lists import parse_list_items, parse_total_pages
from watchlistarr.services.scrape.anti_flap import reconcile_full_scrape
from watchlistarr.services.scrape.film_resolver import resolve_films
from watchlistarr.services.scrape.watchlist import _upsert_items

logger = structlog.get_logger(__name__)


def _path(username: str, slug: str, page: int, *, by_added_earliest: bool = False) -> str:
    base = f"/{username}/list/{slug}/"
    if by_added_earliest:
        base += "by/added-earliest/"
    if page > 1:
        base += f"page/{page}/"
    return base


async def _fetch_owner_and_slug(
    factory: async_sessionmaker[AsyncSession], list_id: int
) -> tuple[str, int, str] | None:
    """Devuelve (username, user_id, list_slug)."""
    async with factory() as session:
        list_row = await session.get(ListModel, list_id)
        if list_row is None:
            return None
        user = await session.get(User, list_row.user_id)
        if user is None:
            return None
        return user.letterboxd_username, user.id, list_row.slug


async def _fetch_all_pages(client: LetterboxdClient, username: str, slug: str) -> list[str]:
    all_slugs: list[str] = []
    page = 1
    total_pages = 1
    while True:
        response = await client.get(_path(username, slug, page))
        html = response.text
        all_slugs.extend(item.slug for item in parse_list_items(html))
        if page == 1:
            total_pages = parse_total_pages(html)
        if page >= total_pages:
            break
        page += 1
    return all_slugs


async def sync_list_full(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    list_id: int,
) -> None:
    owner = await _fetch_owner_and_slug(factory, list_id)
    if owner is None:
        return
    username, user_id, list_slug = owner

    all_slugs = await _fetch_all_pages(client, username, list_slug)
    resolved = await resolve_films(factory, client, all_slugs)

    async with factory() as session:
        list_row: ListModel | None = await session.get(ListModel, list_id)
        if list_row is None:
            return
        await _upsert_items(session, list_id, all_slugs, resolved)
        await reconcile_full_scrape(
            session,
            list_id=list_id,
            user_id=user_id,
            scraped_films=resolved.values(),
            threshold=intervals.list_flap_threshold(list_row, get_settings()),
        )
        list_row.last_synced_at = utcnow()
        list_row.last_sync_status = SyncStatus.SUCCESS
        list_row.film_count = len(resolved)
        await session.commit()

    logger.info(
        "list.full_sync",
        list_id=list_id,
        slug=list_slug,
        slugs=len(all_slugs),
        resolved=len(resolved),
    )


async def sync_list_incremental(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    list_id: int,
) -> None:
    owner = await _fetch_owner_and_slug(factory, list_id)
    if owner is None:
        return
    _username, _user_id, list_slug = owner

    p1_response = await client.get(_path(_username, list_slug, 1))
    total_pages = parse_total_pages(p1_response.text)
    page1_slugs = [item.slug for item in parse_list_items(p1_response.text)]
    if total_pages > 1:
        last_added = await client.get(
            _path(_username, list_slug, total_pages, by_added_earliest=True)
        )
        last_slugs = [item.slug for item in parse_list_items(last_added.text)]
    else:
        last_slugs = []

    combined_slugs: list[str] = []
    seen_slugs: set[str] = set()
    for slug in [*page1_slugs, *last_slugs]:
        if slug in seen_slugs:
            continue
        combined_slugs.append(slug)
        seen_slugs.add(slug)

    resolved = await resolve_films(factory, client, combined_slugs)

    async with factory() as session:
        list_row: ListModel | None = await session.get(ListModel, list_id)
        if list_row is None:
            return
        await _upsert_items(session, list_id, combined_slugs, resolved)
        list_row.last_synced_at = utcnow()
        list_row.last_sync_status = SyncStatus.SUCCESS
        await session.commit()

    logger.info(
        "list.incremental_sync",
        list_id=list_id,
        slug=list_slug,
        slugs=len(combined_slugs),
    )
