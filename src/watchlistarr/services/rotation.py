from __future__ import annotations

import random

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.sublist_items import SublistItem
from watchlistarr.models.sublists import Sublist
from watchlistarr.services.combined import combined_watchlist_tmdb_ids

logger = structlog.get_logger(__name__)


async def _parent_tmdb_ids(session: AsyncSession, sublist: Sublist) -> list[int]:
    if sublist.parent_list_id is not None:
        rows = (
            (
                await session.execute(
                    select(ListItem.tmdb_id).where(ListItem.list_id == sublist.parent_list_id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
    if sublist.parent_combined_kind is not None:
        return await combined_watchlist_tmdb_ids(session, sublist.parent_combined_kind)
    return []


async def eligible_pool(session: AsyncSession, sublist: Sublist) -> list[int]:
    parent_ids = await _parent_tmdb_ids(session, sublist)
    if not parent_ids:
        return []

    filter_query = select(Film.tmdb_id).where(Film.tmdb_id.in_(parent_ids))
    if sublist.min_rating is not None:
        filter_query = filter_query.where(Film.letterboxd_avg_rating >= sublist.min_rating)
    if sublist.max_rating is not None:
        filter_query = filter_query.where(Film.letterboxd_avg_rating <= sublist.max_rating)
    if sublist.min_year is not None:
        filter_query = filter_query.where(Film.year >= sublist.min_year)
    if sublist.max_year is not None:
        filter_query = filter_query.where(Film.year <= sublist.max_year)
    eligible_ids = list((await session.execute(filter_query)).scalars().all())

    if sublist.parent_list_id is not None and (sublist.added_after or sublist.added_before):
        date_query = select(ListItem.tmdb_id).where(
            ListItem.list_id == sublist.parent_list_id,
            ListItem.tmdb_id.in_(eligible_ids),
        )
        if sublist.added_after is not None:
            date_query = date_query.where(ListItem.added_at >= sublist.added_after)
        if sublist.added_before is not None:
            date_query = date_query.where(ListItem.added_at <= sublist.added_before)
        eligible_ids = list((await session.execute(date_query)).scalars().all())

    served = {
        row[0]
        for row in (
            await session.execute(
                select(SublistItem.tmdb_id).where(SublistItem.sublist_id == sublist.id)
            )
        ).all()
    }
    return [t for t in eligible_ids if t not in served]


async def init_sublist_items(session: AsyncSession, sublist: Sublist) -> int:
    pool = await eligible_pool(session, sublist)
    if not pool:
        return 0
    cap = sublist.max_items if sublist.max_items is not None else len(pool)
    chosen = random.sample(pool, min(len(pool), cap))
    now = utcnow()
    for pos, tmdb_id in enumerate(chosen):
        session.add(
            SublistItem(sublist_id=sublist.id, tmdb_id=tmdb_id, served_since=now, position=pos)
        )
    if sublist.rotation_enabled:
        sublist.last_rotated_at = now
    await session.flush()
    logger.info("rotation.init", sublist_id=sublist.id, chosen=len(chosen))
    return len(chosen)


async def recalculate_sublist(session: AsyncSession, sublist: Sublist) -> None:
    """Tras editar filtros o max_items: eliminar los que ya no califican, rellenar."""
    eligible_universe = set(await _parent_tmdb_ids(session, sublist))
    if eligible_universe:
        filter_query = select(Film.tmdb_id).where(Film.tmdb_id.in_(eligible_universe))
        if sublist.min_rating is not None:
            filter_query = filter_query.where(Film.letterboxd_avg_rating >= sublist.min_rating)
        if sublist.max_rating is not None:
            filter_query = filter_query.where(Film.letterboxd_avg_rating <= sublist.max_rating)
        if sublist.min_year is not None:
            filter_query = filter_query.where(Film.year >= sublist.min_year)
        if sublist.max_year is not None:
            filter_query = filter_query.where(Film.year <= sublist.max_year)
        valid = set((await session.execute(filter_query)).scalars().all())
    else:
        valid = set()

    current = list(
        (await session.execute(select(SublistItem).where(SublistItem.sublist_id == sublist.id)))
        .scalars()
        .all()
    )
    for item in current:
        if item.tmdb_id not in valid:
            await session.delete(item)
    await session.flush()

    if sublist.max_items is None:
        return
    remaining = (
        (await session.execute(select(SublistItem).where(SublistItem.sublist_id == sublist.id)))
        .scalars()
        .all()
    )
    if len(list(remaining)) >= sublist.max_items:
        return

    pool = await eligible_pool(session, sublist)
    need = sublist.max_items - len(list(remaining))
    chosen = random.sample(pool, min(len(pool), need))
    now = utcnow()
    for pos, tmdb_id in enumerate(chosen):
        session.add(
            SublistItem(sublist_id=sublist.id, tmdb_id=tmdb_id, served_since=now, position=pos)
        )
    await session.flush()


async def rotate_sublist(session: AsyncSession, sublist: Sublist) -> int:
    if not sublist.rotation_enabled:
        return 0
    now = utcnow()
    if sublist.rotation_interval is None:
        return 0
    if (
        sublist.last_rotated_at is not None
        and sublist.last_rotated_at + sublist.rotation_interval > now
    ):
        return 0

    pool = await eligible_pool(session, sublist)
    if not pool:
        sublist.last_rotated_at = now
        await session.flush()
        return 0

    served = list(
        (
            await session.execute(
                select(SublistItem)
                .where(SublistItem.sublist_id == sublist.id)
                .order_by(SublistItem.served_since)
            )
        )
        .scalars()
        .all()
    )

    batch = min(sublist.rotation_batch_size, len(pool))
    to_remove = served[:batch]
    for item in to_remove:
        await session.delete(item)

    chosen = random.sample(pool, batch)
    for pos, tmdb_id in enumerate(chosen):
        session.add(
            SublistItem(sublist_id=sublist.id, tmdb_id=tmdb_id, served_since=now, position=pos)
        )
    sublist.last_rotated_at = now
    await session.flush()
    logger.info(
        "rotation.tick",
        sublist_id=sublist.id,
        rotated=batch,
    )
    return batch


async def rotation_tick(session: AsyncSession) -> int:
    rows = (
        (await session.execute(select(Sublist).where(Sublist.rotation_enabled.is_(True))))
        .scalars()
        .all()
    )
    rotated = 0
    for sublist in rows:
        rotated += await rotate_sublist(session, sublist)
    return rotated
