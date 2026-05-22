from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import SortOrder
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.schemas.radarr import RadarrItem


async def serialize_list(session: AsyncSession, list_id: int) -> list[RadarrItem]:
    rows = (
        await session.execute(
            select(ListItem.tmdb_id, Film.title, Film.imdb_id)
            .join(Film, ListItem.tmdb_id == Film.tmdb_id)
            .where(ListItem.list_id == list_id)
            .order_by(ListItem.position, ListItem.tmdb_id)
        )
    ).all()
    return [
        RadarrItem(id=tmdb_id, tmdb_id=tmdb_id, title=title, imdb_id=imdb_id)
        for tmdb_id, title, imdb_id in rows
    ]


async def serialize_custom_list(session: AsyncSession, custom_list: CustomList) -> list[RadarrItem]:
    stmt = (
        select(CustomListItem.tmdb_id, Film.title, Film.imdb_id)
        .join(Film, CustomListItem.tmdb_id == Film.tmdb_id)
        .where(CustomListItem.custom_list_id == custom_list.id)
    )
    if custom_list.sort_order is SortOrder.RATING_DESC:
        stmt = stmt.order_by(
            Film.letterboxd_avg_rating.is_(None),
            Film.letterboxd_avg_rating.desc(),
            CustomListItem.position,
        )
    else:
        stmt = stmt.order_by(CustomListItem.position, CustomListItem.tmdb_id)
    if custom_list.max_items is not None:
        stmt = stmt.limit(custom_list.max_items)
    rows = (await session.execute(stmt)).all()
    return [
        RadarrItem(id=tmdb_id, tmdb_id=tmdb_id, title=title, imdb_id=imdb_id)
        for tmdb_id, title, imdb_id in rows
    ]


def render_payload(items: list[RadarrItem]) -> bytes:
    plain = [item.model_dump(exclude_none=True) for item in items]
    return json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_etag(payload: bytes) -> str:
    return f'W/"{hashlib.sha1(payload).hexdigest()}"'
