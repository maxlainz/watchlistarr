from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, or_, select
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
    """List IDs (Letterboxd lists / watchlists) used as sources for ``role``.

    No incluye sources que apuntan a otros custom lists — para eso ver
    :func:`_source_custom_list_ids`.
    """
    rows = (
        await session.execute(
            select(CustomListSource.list_id).where(
                CustomListSource.custom_list_id == custom_list_id,
                CustomListSource.role == role,
                CustomListSource.list_id.is_not(None),
            )
        )
    ).all()
    return [row[0] for row in rows]


async def _source_custom_list_ids(
    session: AsyncSession, custom_list_id: int, role: SourceRole
) -> list[int]:
    """Custom list IDs usados como sources para ``role``."""
    rows = (
        await session.execute(
            select(CustomListSource.source_custom_list_id).where(
                CustomListSource.custom_list_id == custom_list_id,
                CustomListSource.role == role,
                CustomListSource.source_custom_list_id.is_not(None),
            )
        )
    ).all()
    return [row[0] for row in rows]


async def _source_targets(
    session: AsyncSession, custom_list_id: int, role: SourceRole
) -> tuple[list[int], list[int]]:
    """Devuelve ``(list_ids, source_custom_list_ids)`` para ``role``."""
    list_ids = await _source_list_ids(session, custom_list_id, role)
    cl_ids = await _source_custom_list_ids(session, custom_list_id, role)
    return list_ids, cl_ids


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


async def _items_by_custom_list(
    session: AsyncSession, custom_list_ids: list[int]
) -> dict[int, set[int]]:
    """Lee ``custom_list_items.tmdb_id`` agrupado por ``custom_list_id``.

    Devuelve la vista materializada — lo que la custom list sirve a Radarr
    ahora — sin recomputar su universe. Cuando A usa B como source, A ve este
    set: respeta ``max_items``, ``sort_order``, ``snapshot_interval`` y
    rotación de B (coherencia eventual; A se actualiza en su propia tick).
    """
    if not custom_list_ids:
        return {}
    rows = (
        await session.execute(
            select(CustomListItem.custom_list_id, CustomListItem.tmdb_id).where(
                CustomListItem.custom_list_id.in_(custom_list_ids)
            )
        )
    ).all()
    result: dict[int, set[int]] = {cid: set() for cid in custom_list_ids}
    for cl_id, tmdb_id in rows:
        result.setdefault(cl_id, set()).add(tmdb_id)
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
    inc_lists, inc_cls = await _source_targets(session, custom_list.id, SourceRole.INCLUDE)
    sub_lists, sub_cls = await _source_targets(session, custom_list.id, SourceRole.SUBTRACT)
    excluded_users = await _excluded_user_ids(session, custom_list.id)

    by_list = await _items_by_list(session, list(set(inc_lists + sub_lists)))
    by_cl = await _items_by_custom_list(session, list(set(inc_cls + sub_cls)))

    include_sets: list[set[int]] = [by_list.get(lid, set()) for lid in inc_lists]
    include_sets.extend(by_cl.get(cid, set()) for cid in inc_cls)
    includes = _combine_includes(include_sets, custom_list.op)

    subtracts: set[int] = set()
    for lid in sub_lists:
        subtracts |= by_list.get(lid, set())
    for cid in sub_cls:
        subtracts |= by_cl.get(cid, set())

    watched = await _watched_by_users(session, excluded_users)
    return includes - subtracts - watched


async def _apply_filters(
    session: AsyncSession, custom_list: CustomList, tmdb_ids: set[int]
) -> list[int]:
    if not tmdb_ids:
        return []
    now = utcnow()
    if custom_list.year_last_n is not None:
        # Clamp a >=1 — un 0 inyectado vía DB/seed daría year_min > year_max
        # (filtro vacío silencioso). El endpoint ya lo normaliza, pero
        # defendemos al servicio.
        last_n = max(1, custom_list.year_last_n)
        year_min: int | None = now.year - last_n + 1
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
        inc_lists, inc_cls = await _source_targets(session, custom_list.id, SourceRole.INCLUDE)
        if inc_lists or inc_cls:
            # Films que aparecen como ``list_items`` directos en los include
            # ``lists`` deben pasar el filtro de fecha. Los que vienen solo
            # vía custom-list source no tienen ``added_at`` per-source y se
            # conservan sin filtrar (limitación documentada en data-model.md).
            filtered_set = set(filtered)
            from_list_keepers: set[int] = set()
            if inc_lists:
                date_stmt = select(ListItem.tmdb_id).where(
                    ListItem.list_id.in_(inc_lists),
                    ListItem.tmdb_id.in_(filtered_set),
                )
                if added_after_eff is not None:
                    date_stmt = date_stmt.where(ListItem.added_at >= added_after_eff)
                if added_before_eff is not None:
                    date_stmt = date_stmt.where(ListItem.added_at <= added_before_eff)
                from_list_keepers = {row[0] for row in (await session.execute(date_stmt)).all()}

            # tmdb_ids que solo entraron vía custom-list source (no aparecen en
            # ningún list_items de los inc_lists). Pasan sin filtrar.
            only_from_cl: set[int] = set()
            if inc_cls:
                in_lists_stmt = select(ListItem.tmdb_id).where(
                    ListItem.list_id.in_(inc_lists or [-1]),
                    ListItem.tmdb_id.in_(filtered_set),
                )
                in_lists = {row[0] for row in (await session.execute(in_lists_stmt)).all()}
                only_from_cl = filtered_set - in_lists
            filtered = list(from_list_keepers | only_from_cl)
    return filtered


async def _order_pool_by_source_position(
    session: AsyncSession,
    custom_list: CustomList,
    pool: list[int],
    *,
    desc: bool,
) -> list[int]:
    """Devuelve los tmdb_ids del pool ordenados por su posición agregada en
    las include sources del custom list.

    Para ``desc=False`` (LETTERBOXD) usa ``MIN(position)`` ASC — el film toma
    la posición más temprana en cualquiera de sus listas de origen. Para
    ``desc=True`` (REVERSE) usa ``MAX(position)`` DESC — los del final primero.

    Films del pool que no aparezcan en ninguna include source (no debería
    pasar tras ``resolve_universe``) van al final ordenados por ``tmdb_id``.
    """
    if not pool:
        return []
    include_ids = await _source_list_ids(session, custom_list.id, SourceRole.INCLUDE)
    if not include_ids:
        return list(pool)
    agg = func.max(ListItem.position) if desc else func.min(ListItem.position)
    order_clause = agg.desc() if desc else agg.asc()
    rows = (
        await session.execute(
            select(ListItem.tmdb_id, agg.label("pos"))
            .where(ListItem.list_id.in_(include_ids), ListItem.tmdb_id.in_(pool))
            .group_by(ListItem.tmdb_id)
            .order_by(order_clause, ListItem.tmdb_id)
        )
    ).all()
    ordered = [row[0] for row in rows]
    seen = set(ordered)
    leftovers = sorted(t for t in pool if t not in seen)
    return ordered + leftovers


async def _choose_from_pool(
    session: AsyncSession, custom_list: CustomList, pool: list[int], n: int
) -> list[int]:
    """Picks ``n`` tmdb_ids from ``pool`` honoring ``custom_list.sort_order``."""
    if n <= 0 or not pool:
        return []
    sort_order = custom_list.sort_order
    if sort_order is SortOrder.RATING_DESC:
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
    if sort_order is SortOrder.LETTERBOXD:
        ordered = await _order_pool_by_source_position(session, custom_list, pool, desc=False)
        return ordered[:n]
    if sort_order is SortOrder.REVERSE:
        ordered = await _order_pool_by_source_position(session, custom_list, pool, desc=True)
        return ordered[:n]
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
    if custom_list.snapshot_interval is not None:
        custom_list.last_snapshot_at = now
    await session.flush()
    logger.info("custom_list.init", custom_list_id=custom_list.id, chosen=len(chosen))
    return len(chosen)


async def _reindex_positions(session: AsyncSession, custom_list_id: int) -> None:
    """Reasigna ``position`` a [0..N-1] consecutivo.

    Tras delete+insert en ``rotate`` o ``recalculate``, las positions pueden quedar
    duplicadas (los inserts arrancan en 0 mientras los items conservados retienen
    su position original). Orden estable: los más recientes por ``served_since``
    primero — lo que coincide con la intención de poner ítems nuevos al principio.
    """
    items = list(
        (
            await session.execute(
                select(CustomListItem)
                .where(CustomListItem.custom_list_id == custom_list_id)
                .order_by(
                    CustomListItem.served_since.desc(),
                    CustomListItem.position,
                    CustomListItem.tmdb_id,
                )
            )
        )
        .scalars()
        .all()
    )
    for new_pos, item in enumerate(items):
        item.position = new_pos


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

    if custom_list.snapshot_interval is not None:
        custom_list.last_snapshot_at = utcnow()
        await session.flush()

    if custom_list.max_items is None:
        return
    remaining_ids = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListItem.tmdb_id).where(
                    CustomListItem.custom_list_id == custom_list.id
                )
            )
        ).all()
    ]
    remaining_count = len(remaining_ids)
    if remaining_count > custom_list.max_items:
        keep = set(
            await _choose_from_pool(session, custom_list, remaining_ids, custom_list.max_items)
        )
        drop_ids = [t for t in remaining_ids if t not in keep]
        await session.execute(
            delete(CustomListItem).where(
                CustomListItem.custom_list_id == custom_list.id,
                CustomListItem.tmdb_id.in_(drop_ids),
            )
        )
        await session.flush()
        await _reindex_positions(session, custom_list.id)
        await session.flush()
        return
    if remaining_count == custom_list.max_items:
        await _reindex_positions(session, custom_list.id)
        await session.flush()
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
    await _reindex_positions(session, custom_list.id)
    await session.flush()


async def rotate(session: AsyncSession, custom_list: CustomList) -> int:
    if not custom_list.rotation_enabled or custom_list.rotation_interval is None:
        return 0
    now = utcnow()
    last_rotated = custom_list.last_rotated_at
    if last_rotated is not None and last_rotated.tzinfo is None:
        last_rotated = last_rotated.replace(tzinfo=UTC)
    if last_rotated is not None and last_rotated + custom_list.rotation_interval > now:
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
    await _reindex_positions(session, custom_list.id)
    await session.flush()
    logger.info("custom_list.rotated", custom_list_id=custom_list.id, rotated=batch)
    return batch


async def refresh_snapshot(session: AsyncSession, custom_list: CustomList) -> int:
    """Regenera el set completo de items respetando filtros, sources y sort_order
    actuales. Reemplaza atómicamente ``custom_list_items``.

    Si la custom list está en modo snapshot (``snapshot_interval`` not None),
    skipea silenciosamente cuando aún no ha pasado el cooldown desde el último
    refresh.
    """
    if custom_list.snapshot_interval is None:
        return 0
    now = utcnow()
    last = custom_list.last_snapshot_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if last is not None and last + custom_list.snapshot_interval > now:
        return 0
    await session.execute(
        delete(CustomListItem).where(CustomListItem.custom_list_id == custom_list.id)
    )
    await session.flush()
    count = await init_items(session, custom_list)
    # ``init_items`` ya stampa ``last_snapshot_at`` cuando snapshot_interval no es None,
    # pero pool vacío hace early-return sin stamp. Stampar también aquí para evitar
    # loop de refresh tras pool vacío transitorio.
    custom_list.last_snapshot_at = now
    await session.flush()
    logger.info("custom_list.snapshot_refreshed", custom_list_id=custom_list.id, items=count)
    return count


async def rotation_tick(session: AsyncSession) -> int:
    rows = (
        (
            await session.execute(
                select(CustomList).where(
                    or_(
                        CustomList.rotation_enabled.is_(True),
                        CustomList.snapshot_interval.is_not(None),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    handled = 0
    for custom_list in rows:
        if custom_list.snapshot_interval is not None:
            # Snapshot prevalece sobre rotation: el refresh completo hace inútil
            # el cycle parcial.
            handled += await refresh_snapshot(session, custom_list)
        else:
            handled += await rotate(session, custom_list)
    return handled


async def describe_sources(session: AsyncSession, custom_list: CustomList) -> str:
    """Human-readable summary of the sources for UI tables."""
    from watchlistarr.models.enums import SourceType
    from watchlistarr.models.lists import List as ListModel
    from watchlistarr.models.users import User

    inc_lists, inc_cls = await _source_targets(session, custom_list.id, SourceRole.INCLUDE)
    sub_lists, sub_cls = await _source_targets(session, custom_list.id, SourceRole.SUBTRACT)
    excluded_user_ids = await _excluded_user_ids(session, custom_list.id)

    if not inc_lists and not inc_cls:
        return "no sources"

    list_ids_all = list({*inc_lists, *sub_lists})
    list_rows = (
        (
            (await session.execute(select(ListModel).where(ListModel.id.in_(list_ids_all))))
            .scalars()
            .all()
        )
        if list_ids_all
        else []
    )
    list_by_id = {lst.id: lst for lst in list_rows}
    user_ids = {lst.user_id for lst in list_rows}
    users_map = (
        {
            u.id: u.letterboxd_username
            for u in (
                (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
            )
        }
        if user_ids
        else {}
    )

    cl_ids_all = list({*inc_cls, *sub_cls})
    cl_rows = (
        (
            (await session.execute(select(CustomList).where(CustomList.id.in_(cl_ids_all))))
            .scalars()
            .all()
        )
        if cl_ids_all
        else []
    )
    cl_by_id = {cl.id: cl for cl in cl_rows}

    def _list_label(lst: ListModel) -> str:
        owner = users_map.get(lst.user_id, "?")
        if lst.source_type is SourceType.WATCHLIST:
            return f"{owner}/watchlist"
        return f"{owner}/{lst.slug}"

    include_labels = [_list_label(list_by_id[lid]) for lid in inc_lists if lid in list_by_id]
    include_labels.extend(f"cl:{cl_by_id[cid].slug}" for cid in inc_cls if cid in cl_by_id)
    parts = [f"{custom_list.op.value} of " + ", ".join(include_labels)]

    if sub_lists or sub_cls:
        sub_labels = [_list_label(list_by_id[lid]) for lid in sub_lists if lid in list_by_id]
        sub_labels.extend(f"cl:{cl_by_id[cid].slug}" for cid in sub_cls if cid in cl_by_id)
        parts.append("minus " + ", ".join(sub_labels))

    if excluded_user_ids:
        excluded_users = (
            (await session.execute(select(User).where(User.id.in_(excluded_user_ids))))
            .scalars()
            .all()
        )
        parts.append("excl. watched by " + ", ".join(u.letterboxd_username for u in excluded_users))
    return "; ".join(parts)


async def detect_cycle(
    session: AsyncSession,
    target_custom_list_id: int | None,
    candidate_source_ids: list[int],
) -> int | None:
    """Devuelve el id de un custom list que cierra ciclo, o None.

    BFS por ``custom_list_sources.source_custom_list_id`` arrancando en
    ``candidate_source_ids`` (los custom-list-sources que se quieren añadir a
    ``target_custom_list_id``). Si la travesía alcanza ``target_custom_list_id``
    → ciclo. Si ``target_custom_list_id`` es None (creación), solo se detecta
    self-reference vía ids inválidos — el caller debe haber filtrado eso
    aparte (no se conoce el id aún).
    """
    if not candidate_source_ids:
        return None
    if target_custom_list_id is not None and target_custom_list_id in candidate_source_ids:
        return target_custom_list_id

    visited: set[int] = set()
    frontier: list[int] = list(set(candidate_source_ids))

    while frontier:
        if target_custom_list_id is not None and target_custom_list_id in frontier:
            return target_custom_list_id
        next_frontier: list[int] = []
        rows = (
            await session.execute(
                select(
                    CustomListSource.custom_list_id,
                    CustomListSource.source_custom_list_id,
                ).where(
                    CustomListSource.custom_list_id.in_(frontier),
                    CustomListSource.source_custom_list_id.is_not(None),
                )
            )
        ).all()
        visited.update(frontier)
        for _parent_id, child_id in rows:
            if child_id is None or child_id in visited:
                continue
            cid = int(child_id)
            if target_custom_list_id is not None and cid == target_custom_list_id:
                return cid
            next_frontier.append(cid)
        frontier = list(set(next_frontier))
    return None
