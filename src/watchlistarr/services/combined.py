from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.enums import CombinedKind, SourceType
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm


async def _union(session: AsyncSession) -> list[int]:
    stmt = (
        select(ListItem.tmdb_id, func.min(ListItem.position).label("min_pos"))
        .join(ListModel, ListItem.list_id == ListModel.id)
        .where(ListModel.source_type == SourceType.WATCHLIST)
        .group_by(ListItem.tmdb_id)
        .order_by("min_pos", ListItem.tmdb_id)
    )
    return [row[0] for row in (await session.execute(stmt)).all()]


async def _intersection(session: AsyncSession) -> list[int]:
    total_users = (await session.execute(select(func.count(User.id)))).scalar_one()
    if total_users == 0:
        return []
    stmt = (
        select(ListItem.tmdb_id)
        .join(ListModel, ListItem.list_id == ListModel.id)
        .where(ListModel.source_type == SourceType.WATCHLIST)
        .group_by(ListItem.tmdb_id)
        .having(func.count(func.distinct(ListModel.user_id)) == total_users)
        .order_by(ListItem.tmdb_id)
    )
    return [row[0] for row in (await session.execute(stmt)).all()]


async def _union_unwatched(session: AsyncSession) -> list[int]:
    watched_subq = select(WatchedFilm.tmdb_id).distinct().scalar_subquery()
    stmt = (
        select(ListItem.tmdb_id)
        .join(ListModel, ListItem.list_id == ListModel.id)
        .where(
            ListModel.source_type == SourceType.WATCHLIST,
            ListItem.tmdb_id.not_in(watched_subq),
        )
        .distinct()
        .order_by(ListItem.tmdb_id)
    )
    return [row[0] for row in (await session.execute(stmt)).all()]


async def combined_watchlist_tmdb_ids(session: AsyncSession, kind: CombinedKind) -> list[int]:
    if kind is CombinedKind.UNION:
        return await _union(session)
    if kind is CombinedKind.INTERSECTION:
        return await _intersection(session)
    if kind is CombinedKind.UNION_UNWATCHED:
        return await _union_unwatched(session)
    raise ValueError(f"combinada no soportada: {kind!r}")


async def films_by_tmdb_ids(session: AsyncSession, tmdb_ids: list[int]) -> dict[int, Film]:
    if not tmdb_ids:
        return {}
    rows = (await session.execute(select(Film).where(Film.tmdb_id.in_(tmdb_ids)))).scalars().all()
    return {film.tmdb_id: film for film in rows}
