from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.schemas.letterboxd import DiscoveredList
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.lists import parse_lists_index, parse_total_pages

logger = structlog.get_logger(__name__)


async def _fetch_all_pages(client: LetterboxdClient, username: str) -> list[DiscoveredList]:
    discovered: list[DiscoveredList] = []
    page = 1
    total_pages = 1
    while True:
        path = f"/{username}/lists/" if page == 1 else f"/{username}/lists/page/{page}/"
        response = await client.get(path)
        html = response.text
        discovered.extend(parse_lists_index(html))
        if page == 1:
            total_pages = parse_total_pages(html)
        if page >= total_pages:
            break
        page += 1
    return discovered


async def _persist(
    session: AsyncSession,
    user_id: int,
    discovered: list[DiscoveredList],
) -> list[ListModel]:
    seen_ids = {d.letterboxd_list_id for d in discovered}

    existing = list(
        (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id == user_id,
                    ListModel.source_type == SourceType.LIST,
                )
            )
        )
        .scalars()
        .all()
    )
    existing_by_id = {row.letterboxd_list_id: row for row in existing if row.letterboxd_list_id}

    upserted: list[ListModel] = []
    for entry in discovered:
        row = existing_by_id.get(entry.letterboxd_list_id)
        if row is None:
            row = ListModel(
                user_id=user_id,
                source_type=SourceType.LIST,
                letterboxd_list_id=entry.letterboxd_list_id,
                slug=entry.slug,
                name=entry.name,
                film_count=entry.film_count,
                enabled=False,
            )
            session.add(row)
            logger.info(
                "discovery.new_list",
                user_id=user_id,
                slug=entry.slug,
                letterboxd_id=entry.letterboxd_list_id,
            )
        else:
            row.slug = entry.slug
            row.name = entry.name
            row.film_count = entry.film_count
        upserted.append(row)

    for row in existing:
        if row.letterboxd_list_id and row.letterboxd_list_id not in seen_ids and row.enabled:
            logger.info(
                "discovery.disabled_missing",
                user_id=user_id,
                slug=row.slug,
                letterboxd_id=row.letterboxd_list_id,
            )
            row.enabled = False

    await session.flush()
    return upserted


async def discover_lists(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    user: User,
) -> list[ListModel]:
    discovered = await _fetch_all_pages(client, user.letterboxd_username)

    async with factory() as session:
        upserted = await _persist(session, user.id, discovered)
        await session.commit()
    return upserted
