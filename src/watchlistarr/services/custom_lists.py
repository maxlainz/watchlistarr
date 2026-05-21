from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.custom_list_excluded_watchers import CustomListExcludedWatcher
from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import CombinationOp, SortOrder, SourceRole
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.watched_films import WatchedFilm

logger = structlog.get_logger(__name__)


async def _source_list_ids(
    session: AsyncSession, custom_list_id: int, role: SourceRole
) -> list[int]:
    rows = (
        await session.execute(
            select(CustomListSource.list_id).where(
                CustomListSource.custom_list_id == custom_list_id,
                CustomListSource.role == role,
            )
        )
    ).all()
    return [row[0] for row in rows]


async def _excluded_user_ids(session: AsyncSession, custom_list_id: int) -> list[int]:
    rows = (
        await session.execute(
            select(CustomListExcludedWatcher.user_id).where(
                CustomListExcludedWatcher.custom_list_id == custom_list_id
            )
        )
    ).all()
    return [row[0] for row in rows]


async def _items_by_list(session: AsyncSession, list_ids: list[int]) -> dict[int, set[int]]:
    if not list_ids:
        return {}
    rows = (
        await session.execute(
            select(ListItem.list_id, ListItem.tmdb_id).where(ListItem.list_id.in_(list_ids))
        )
    ).all()
    result: dict[int, set[int]] = {lid: set() for lid in list_ids}
    for list_id, tmdb_id in rows:
        result.setdefault(list_id, set()).add(tmdb_id)
    return result


async def _watched_by_users(session: AsyncSession, user_ids: list[int]) -> set[int]:
    if not user_ids:
        return set()
    rows = (
        await session.execute(select(WatchedFilm.tmdb_id).where(WatchedFilm.user_id.in_(user_ids)))
    ).all()
    return {row[0] for row in rows}


def _combine_includes(per_list: Iterable[set[int]], op: CombinationOp) -> set[int]:
    sets = list(per_list)
    if not sets:
        return set()
    if op is CombinationOp.UNION:
        return set().union(*sets)
    base = sets[0].copy()
    for s in sets[1:]:
        base &= s
    return base


async def resolve_universe(session: AsyncSession, custom_list: CustomList) -> set[int]:
    """Conjunto base de tmdb_ids antes de aplicar filtros estáticos."""
    include_ids = await _source_list_ids(session, custom_list.id, SourceRole.INCLUDE)
    subtract_ids = await _source_list_ids(session, custom_list.id, SourceRole.SUBTRACT)
    excluded_users = await _excluded_user_ids(session, custom_list.id)

    by_list = await _items_by_list(session, list(set(include_ids + subtract_ids)))
    includes = _combine_includes((by_list.get(lid, set()) for lid in include_ids), custom_list.op)
    subtracts: set[int] = set()
    for lid in subtract_ids:
        subtracts |= by_list.get(lid, set())
    watched = await _watched_by_users(session, excluded_users)
    return includes - subtracts - watched


async def _apply_filters(
    session: AsyncSession, custom_list: CustomList, tmdb_ids: set[int]
) -> list[int]:
    if not tmdb_ids:
        return []
    now = utcnow()
    if custom_list.year_last_n is not None:
        year_min: int | None = now.year - custom_list.year_last_n + 1
        year_max: int | None = now.year
    else:
        year_min = custom_list.min_year
        year_max = custom_list.max_year
    added_after_eff: datetime | None
    added_before_eff: datetime | None
    if custom_list.added_last_n_days is not None:
        added_after_eff = now - timedelta(days=custom_list.added_last_n_days)
        added_before_eff = None
    else:
        added_after_eff = custom_list.added_after
        added_before_eff = custom_list.added_before

    stmt = select(Film.tmdb_id).where(Film.tmdb_id.in_(tmdb_ids))
    if custom_list.min_rating is not None:
        stmt = stmt.where(Film.letterboxd_avg_rating >= custom_list.min_rating)
    if custom_list.max_rating is not None:
        stmt = stmt.where(Film.letterboxd_avg_rating <= custom_list.max_rating)
    if year_min is not None:
        stmt = stmt.where(Film.year >= year_min)
    if year_max is not None:
        stmt = stmt.where(Film.year <= year_max)
    filtered = [row[0] for row in (await session.execute(stmt)).all()]

    if added_after_eff is not None or added_before_eff is not None:
        include_ids = await _source_list_ids(session, custom_list.id, SourceRole.INCLUDE)
        if include_ids:
            date_stmt = select(ListItem.tmdb_id).where(
                ListItem.list_id.in_(include_ids), ListItem.tmdb_id.in_(filtered)
            )
            if added_after_eff is not None:
                date_stmt = date_stmt.where(ListItem.added_at >= added_after_eff)
            if added_before_eff is not None:
                date_stmt = date_stmt.where(ListItem.added_at <= added_before_eff)
            filtered = list({row[0] for row in (await session.execute(date_stmt)).all()})
    return filtered


async def _choose_from_pool(
    session: AsyncSession, custom_list: CustomList, pool: list[int], n: int
) -> list[int]:
    """Picks ``n`` tmdb_ids from ``pool`` honoring ``custom_list.sort_order``.

    For RATING_DESC, returns the top-N by ``Film.letterboxd_avg_rating`` (NULLs last).
    For every other sort order, falls back to ``random.sample`` (legacy behavior).
    """
    if n <= 0 or not pool:
        return []
    if custom_list.sort_order is SortOrder.RATING_DESC:
        rows = (
            await session.execute(
                select(Film.tmdb_id)
                .where(Film.tmdb_id.in_(pool))
                .order_by(
                    Film.letterboxd_avg_rating.is_(None),
                    Film.letterboxd_avg_rating.desc(),
                    Film.tmdb_id,
                )
                .limit(n)
            )
        ).all()
        return [row[0] for row in rows]
    return random.sample(pool, min(len(pool), n))


async def eligible_pool(session: AsyncSession, custom_list: CustomList) -> list[int]:
    universe = await resolve_universe(session, custom_list)
    candidates = await _apply_filters(session, custom_list, universe)
    served = {
        row[0]
        for row in (
            await session.execute(
                select(CustomListItem.tmdb_id).where(
                    CustomListItem.custom_list_id == custom_list.id
                )
            )
        ).all()
    }
    return [t for t in candidates if t not in served]


async def resolve_full_pool(session: AsyncSession, custom_list: CustomList) -> list[int]:
    """Tmdb_ids elegibles incluyendo ya servidos. Útil para mostrar tamaño total."""
    universe = await resolve_universe(session, custom_list)
    return await _apply_filters(session, custom_list, universe)


async def init_items(session: AsyncSession, custom_list: CustomList) -> int:
    pool = await eligible_pool(session, custom_list)
    if not pool:
        return 0
    cap = custom_list.max_items if custom_list.max_items is not None else len(pool)
    chosen = await _choose_from_pool(session, custom_list, pool, cap)
    now = utcnow()
    for pos, tmdb_id in enumerate(chosen):
        session.add(
            CustomListItem(
                custom_list_id=custom_list.id,
                tmdb_id=tmdb_id,
                served_since=now,
                position=pos,
            )
        )
    if custom_list.rotation_enabled:
        custom_list.last_rotated_at = now
    await session.flush()
    logger.info("custom_list.init", custom_list_id=custom_list.id, chosen=len(chosen))
    return len(chosen)


async def recalculate(session: AsyncSession, custom_list: CustomList) -> None:
    """Tras editar filtros / sources / max_items: eliminar lo que ya no califica,
    rellenar hasta max_items con elementos del pool restante."""
    candidates = set(
        await _apply_filters(session, custom_list, await resolve_universe(session, custom_list))
    )
    current = list(
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == custom_list.id)
            )
        )
        .scalars()
        .all()
    )
    for item in current:
        if item.tmdb_id not in candidates:
            await session.delete(item)
    await session.flush()

    if custom_list.max_items is None:
        return
    remaining_count = len(
        list(
            (
                await session.execute(
                    select(CustomListItem.tmdb_id).where(
                        CustomListItem.custom_list_id == custom_list.id
                    )
                )
            ).all()
        )
    )
    if remaining_count >= custom_list.max_items:
        return
    pool = await eligible_pool(session, custom_list)
    need = custom_list.max_items - remaining_count
    chosen = await _choose_from_pool(session, custom_list, pool, need)
    now = utcnow()
    for pos, tmdb_id in enumerate(chosen, start=remaining_count):
        session.add(
            CustomListItem(
                custom_list_id=custom_list.id,
                tmdb_id=tmdb_id,
                served_since=now,
                position=pos,
            )
        )
    await session.flush()


async def rotate(session: AsyncSession, custom_list: CustomList) -> int:
    if not custom_list.rotation_enabled or custom_list.rotation_interval is None:
        return 0
    now = utcnow()
    if (
        custom_list.last_rotated_at is not None
        and custom_list.last_rotated_at + custom_list.rotation_interval > now
    ):
        return 0
    pool = await eligible_pool(session, custom_list)
    if not pool:
        custom_list.last_rotated_at = now
        await session.flush()
        return 0
    served = list(
        (
            await session.execute(
                select(CustomListItem)
                .where(CustomListItem.custom_list_id == custom_list.id)
                .order_by(CustomListItem.served_since)
            )
        )
        .scalars()
        .all()
    )
    batch = min(custom_list.rotation_batch_size, len(pool))
    for item in served[:batch]:
        await session.delete(item)
    chosen = await _choose_from_pool(session, custom_list, pool, batch)
    for pos, tmdb_id in enumerate(chosen):
        session.add(
            CustomListItem(
                custom_list_id=custom_list.id,
                tmdb_id=tmdb_id,
                served_since=now,
                position=pos,
            )
        )
    custom_list.last_rotated_at = now
    await session.flush()
    logger.info("custom_list.rotated", custom_list_id=custom_list.id, rotated=batch)
    return batch


async def rotation_tick(session: AsyncSession) -> int:
    rows = (
        (await session.execute(select(CustomList).where(CustomList.rotation_enabled.is_(True))))
        .scalars()
        .all()
    )
    rotated = 0
    for custom_list in rows:
        rotated += await rotate(session, custom_list)
    return rotated


async def describe_sources(session: AsyncSession, custom_list: CustomList) -> str:
    """Human-readable summary of the sources for UI tables."""
    from watchlistarr.models.enums import SourceType
    from watchlistarr.models.lists import List as ListModel
    from watchlistarr.models.users import User

    include_ids = await _source_list_ids(session, custom_list.id, SourceRole.INCLUDE)
    subtract_ids = await _source_list_ids(session, custom_list.id, SourceRole.SUBTRACT)
    excluded_user_ids = await _excluded_user_ids(session, custom_list.id)

    if not include_ids:
        return "no sources"

    list_rows = (
        (await session.execute(select(ListModel).where(ListModel.id.in_(include_ids))))
        .scalars()
        .all()
    )
    user_ids = {lst.user_id for lst in list_rows}
    users_map = {
        u.id: u.letterboxd_username
        for u in (
            (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        )
    }

    def _label(lst: ListModel) -> str:
        owner = users_map.get(lst.user_id, "?")
        if lst.source_type is SourceType.WATCHLIST:
            return f"{owner}/watchlist"
        return f"{owner}/{lst.slug}"

    include_labels = [_label(lst) for lst in list_rows]
    parts = [f"{custom_list.op.value} of " + ", ".join(include_labels)]

    if subtract_ids:
        sub_rows = (
            (await session.execute(select(ListModel).where(ListModel.id.in_(subtract_ids))))
            .scalars()
            .all()
        )
        sub_user_ids = {lst.user_id for lst in sub_rows}
        sub_users = {
            u.id: u.letterboxd_username
            for u in (
                (await session.execute(select(User).where(User.id.in_(sub_user_ids))))
                .scalars()
                .all()
            )
        }

        def _sub_label(lst: ListModel) -> str:
            owner = sub_users.get(lst.user_id, "?")
            if lst.source_type is SourceType.WATCHLIST:
                return f"{owner}/watchlist"
            return f"{owner}/{lst.slug}"

        parts.append("minus " + ", ".join(_sub_label(lst) for lst in sub_rows))

    if excluded_user_ids:
        excluded_users = (
            (await session.execute(select(User).where(User.id.in_(excluded_user_ids))))
            .scalars()
            .all()
        )
        parts.append("excl. watched by " + ", ".join(u.letterboxd_username for u in excluded_users))
    return "; ".join(parts)
