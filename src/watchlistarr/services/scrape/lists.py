from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import get_settings
from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import SyncStatus
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services import intervals
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.lists import parse_list_items, parse_total_pages
from watchlistarr.services.scrape.anti_flap import reconcile_full_scrape
from watchlistarr.services.scrape.watchlist import _resolve_slugs, _upsert_items

logger = structlog.get_logger(__name__)


def _path(username: str, slug: str, page: int, *, by_added_earliest: bool = False) -> str:
    base = f"/{username}/list/{slug}/"
    if by_added_earliest:
        base += "by/added-earliest/"
    if page > 1:
        base += f"page/{page}/"
    return base


async def sync_list_full(
    session: AsyncSession, client: LetterboxdClient, list_row: ListModel
) -> None:
    user = await session.get(User, list_row.user_id)
    if user is None:
        return

    all_slugs: list[str] = []
    page = 1
    total_pages = 1
    while True:
        response = await client.get(_path(user.letterboxd_username, list_row.slug, page))
        html = response.text
        all_slugs.extend(item.slug for item in parse_list_items(html))
        if page == 1:
            total_pages = parse_total_pages(html)
        if page >= total_pages:
            break
        page += 1

    films_by_slug = await _resolve_slugs(session, client, all_slugs)
    await _upsert_items(session, list_row.id, all_slugs, films_by_slug)

    await reconcile_full_scrape(
        session,
        list_id=list_row.id,
        user_id=list_row.user_id,
        scraped_films=films_by_slug.values(),
        threshold=intervals.list_flap_threshold(list_row, get_settings()),
    )

    list_row.last_synced_at = utcnow()
    list_row.last_sync_status = SyncStatus.SUCCESS
    list_row.film_count = len(films_by_slug)
    await session.flush()
    logger.info(
        "list.full_sync",
        list_id=list_row.id,
        slug=list_row.slug,
        slugs=len(all_slugs),
        resolved=len(films_by_slug),
    )


async def sync_list_incremental(
    session: AsyncSession, client: LetterboxdClient, list_row: ListModel
) -> None:
    user = await session.get(User, list_row.user_id)
    if user is None:
        return

    p1_response = await client.get(_path(user.letterboxd_username, list_row.slug, 1))
    total_pages = parse_total_pages(p1_response.text)
    page1_slugs = [item.slug for item in parse_list_items(p1_response.text)]
    if total_pages > 1:
        last_added = await client.get(
            _path(user.letterboxd_username, list_row.slug, total_pages, by_added_earliest=True)
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

    films_by_slug = await _resolve_slugs(session, client, combined_slugs)
    await _upsert_items(session, list_row.id, combined_slugs, films_by_slug)
    list_row.last_synced_at = utcnow()
    list_row.last_sync_status = SyncStatus.SUCCESS
    await session.flush()
    logger.info(
        "list.incremental_sync",
        list_id=list_row.id,
        slug=list_row.slug,
        slugs=len(combined_slugs),
    )
