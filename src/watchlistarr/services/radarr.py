from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.sublist_items import SublistItem
from watchlistarr.schemas.radarr import RadarrItem
from watchlistarr.services.combined import films_by_tmdb_ids


async def serialize_list(session: AsyncSession, list_id: int) -> list[RadarrItem]:
    rows = (
        await session.execute(
            select(ListItem.tmdb_id, Film.title)
            .join(Film, ListItem.tmdb_id == Film.tmdb_id)
            .where(ListItem.list_id == list_id)
            .order_by(ListItem.position, ListItem.tmdb_id)
        )
    ).all()
    return [RadarrItem(tmdb_id=tmdb_id, title=title) for tmdb_id, title in rows]


async def serialize_sublist(session: AsyncSession, sublist_id: int) -> list[RadarrItem]:
    rows = (
        await session.execute(
            select(SublistItem.tmdb_id, Film.title)
            .join(Film, SublistItem.tmdb_id == Film.tmdb_id)
            .where(SublistItem.sublist_id == sublist_id)
            .order_by(SublistItem.position, SublistItem.tmdb_id)
        )
    ).all()
    return [RadarrItem(tmdb_id=tmdb_id, title=title) for tmdb_id, title in rows]


async def serialize_combined(session: AsyncSession, tmdb_ids: list[int]) -> list[RadarrItem]:
    films = await films_by_tmdb_ids(session, tmdb_ids)
    items: list[RadarrItem] = []
    for tmdb_id in tmdb_ids:
        film = films.get(tmdb_id)
        items.append(RadarrItem(tmdb_id=tmdb_id, title=film.title if film else None))
    return items


def render_payload(items: list[RadarrItem]) -> bytes:
    plain = [item.model_dump(exclude_none=True) for item in items]
    return json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_etag(payload: bytes) -> str:
    return f'W/"{hashlib.sha1(payload).hexdigest()}"'
