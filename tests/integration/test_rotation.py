from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.base import utcnow
from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import CombinationOp, SortOrder, SourceRole, SourceType
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.custom_lists import (
    eligible_pool,
    init_items,
    recalculate,
    refresh_snapshot,
    resolve_full_pool,
    rotate,
    rotation_tick,
)
from watchlistarr.services.radarr import serialize_custom_list


async def _seed_user_list(
    session: AsyncSession, tmdb_ids: list[int], year: int = 2020
) -> tuple[User, ListModel]:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    parent = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="WL",
        enabled=True,
    )
    session.add(parent)
    await session.flush()
    for pos, tmdb_id in enumerate(tmdb_ids):
        session.add(
            Film(
                tmdb_id=tmdb_id,
                letterboxd_slug=f"f{tmdb_id}",
                title=f"Film {tmdb_id}",
                year=year,
            )
        )
        session.add(ListItem(list_id=parent.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()
    return user, parent


async def _make_custom_list(
    session: AsyncSession, parent: ListModel, **kwargs: object
) -> CustomList:
    defaults: dict[str, object] = {
        "slug": "top",
        "name": "Top",
        "op": CombinationOp.UNION,
        "sort_order": SortOrder.LETTERBOXD,
        "rotation_enabled": False,
        "rotation_batch_size": 1,
        "enabled": True,
    }
    defaults.update(kwargs)
    cl = CustomList(**defaults)  # type: ignore[arg-type]
    session.add(cl)
    await session.flush()
    session.add(CustomListSource(custom_list_id=cl.id, list_id=parent.id, role=SourceRole.INCLUDE))
    await session.flush()
    return cl


async def test_init_items_picks_random_subset(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    cl = await _make_custom_list(session, parent, max_items=3)

    count = await init_items(session, cl)
    assert count == 3
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(list(items)) == 3


async def test_eligible_pool_excludes_already_served(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3])
    cl = await _make_custom_list(session, parent, slug="served", max_items=2)
    session.add(CustomListItem(custom_list_id=cl.id, tmdb_id=1, position=0))
    await session.flush()

    pool = await eligible_pool(session, cl)
    assert sorted(pool) == [2, 3]


async def test_recalculate_drops_invalid_and_refills(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3, 4], year=2010)
    film2 = await session.get(Film, 2)
    assert film2 is not None
    film2.year = 1990
    cl = await _make_custom_list(session, parent, slug="modern", max_items=3, min_year=2000)
    session.add_all(
        [
            CustomListItem(custom_list_id=cl.id, tmdb_id=1, position=0),
            CustomListItem(custom_list_id=cl.id, tmdb_id=2, position=1),
        ]
    )
    await session.flush()

    await recalculate(session, cl)
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    assert 2 not in tmdb_ids
    assert len(tmdb_ids) == 3


async def test_recalculate_truncates_when_max_items_lowered(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    cl = await _make_custom_list(session, parent, slug="shrink", max_items=5)
    await init_items(session, cl)
    cl.max_items = 2
    await session.flush()

    await recalculate(session, cl)
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(list(items)) == 2


async def test_recalculate_truncate_respects_rating_sort(session: AsyncSession) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    parent = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="WL",
        enabled=True,
    )
    session.add(parent)
    await session.flush()
    rating_by_tmdb = {1: 4.5, 2: 4.0, 3: 3.5, 4: 3.0, 5: 2.5}
    for pos, (tmdb_id, rating) in enumerate(rating_by_tmdb.items()):
        session.add(
            Film(
                tmdb_id=tmdb_id,
                letterboxd_slug=f"f{tmdb_id}",
                title=f"Film {tmdb_id}",
                year=2020,
                letterboxd_avg_rating=rating,
            )
        )
        session.add(ListItem(list_id=parent.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()

    cl = await _make_custom_list(
        session, parent, slug="shrink-rating", max_items=5, sort_order=SortOrder.RATING_DESC
    )
    await init_items(session, cl)
    cl.max_items = 2
    await session.flush()

    await recalculate(session, cl)
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(it.tmdb_id for it in items) == [1, 2]


async def test_serialize_custom_list_respects_max_items_limit(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session, parent, slug="serve-cap", max_items=3, sort_order=SortOrder.LETTERBOXD
    )
    for pos, tmdb_id in enumerate([10, 20, 30, 40, 50]):
        session.add(CustomListItem(custom_list_id=cl.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()

    items = await serialize_custom_list(session, cl)
    assert len(items) == 3
    assert [it.tmdb_id for it in items] == [10, 20, 30]


async def test_rotate_respects_interval(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    cl = await _make_custom_list(
        session,
        parent,
        slug="rot",
        max_items=2,
        rotation_enabled=True,
        rotation_interval=timedelta(days=7),
        rotation_batch_size=1,
        last_rotated_at=utcnow(),
    )
    session.add_all(
        [
            CustomListItem(custom_list_id=cl.id, tmdb_id=1, position=0),
            CustomListItem(custom_list_id=cl.id, tmdb_id=2, position=1),
        ]
    )
    await session.flush()

    rotated = await rotate(session, cl)
    assert rotated == 0


async def test_letterboxd_sort_picks_top_of_source_order(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session, parent, slug="top-letterboxd", max_items=3, sort_order=SortOrder.LETTERBOXD
    )
    await init_items(session, cl)
    items = await serialize_custom_list(session, cl)
    assert [it.tmdb_id for it in items] == [10, 20, 30]


async def test_reverse_sort_picks_bottom_of_source_order(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session, parent, slug="reverse-list", max_items=3, sort_order=SortOrder.REVERSE
    )
    await init_items(session, cl)
    items = await serialize_custom_list(session, cl)
    assert [it.tmdb_id for it in items] == [50, 40, 30]


async def test_random_sort_returns_full_subset(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session, parent, slug="rand", max_items=3, sort_order=SortOrder.RANDOM
    )
    count = await init_items(session, cl)
    assert count == 3
    items = await serialize_custom_list(session, cl)
    assert len(items) == 3
    assert {it.tmdb_id for it in items}.issubset({10, 20, 30, 40, 50})


async def test_year_last_n_uses_relative_window(session: AsyncSession) -> None:
    current_year = utcnow().year
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    parent = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="WL",
        enabled=True,
    )
    session.add(parent)
    await session.flush()
    year_by_tmdb = {
        1: current_year,
        2: current_year - 1,
        3: current_year - 2,
        4: current_year - 10,
    }
    for pos, (tmdb_id, year) in enumerate(year_by_tmdb.items()):
        session.add(
            Film(
                tmdb_id=tmdb_id,
                letterboxd_slug=f"f{tmdb_id}",
                title=f"Film {tmdb_id}",
                year=year,
            )
        )
        session.add(ListItem(list_id=parent.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()

    cl = await _make_custom_list(session, parent, slug="recent", year_last_n=1)
    pool = await resolve_full_pool(session, cl)
    assert sorted(pool) == [1]

    cl.year_last_n = 3
    await session.flush()
    pool = await resolve_full_pool(session, cl)
    assert sorted(pool) == [1, 2, 3]


async def test_year_last_n_zero_clamps_to_one(session: AsyncSession) -> None:
    """Regresión: ``year_last_n=0`` inyectado en DB no debe dar pool vacío.
    Antes producía ``year_min = current+1 > year_max = current``."""
    current_year = utcnow().year
    _, parent = await _seed_user_list(session, [1], year=current_year)
    cl = await _make_custom_list(session, parent, slug="clamp", year_last_n=0)
    pool = await resolve_full_pool(session, cl)
    assert pool == [1]


async def test_year_last_n_overrides_min_max_year(session: AsyncSession) -> None:
    current_year = utcnow().year
    _, parent = await _seed_user_list(session, [1], year=current_year)
    cl = await _make_custom_list(
        session, parent, slug="override", min_year=1900, max_year=1950, year_last_n=2
    )
    pool = await resolve_full_pool(session, cl)
    assert sorted(pool) == [1]


async def test_rating_desc_picks_top_and_serves_in_order(session: AsyncSession) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    parent = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="WL",
        enabled=True,
    )
    session.add(parent)
    await session.flush()
    rating_by_tmdb = {1: 4.5, 2: 4.0, 3: 3.5, 4: 3.0, 5: None}
    for pos, (tmdb_id, rating) in enumerate(rating_by_tmdb.items()):
        session.add(
            Film(
                tmdb_id=tmdb_id,
                letterboxd_slug=f"f{tmdb_id}",
                title=f"Film {tmdb_id}",
                year=2020,
                letterboxd_avg_rating=rating,
            )
        )
        session.add(ListItem(list_id=parent.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()

    cl = await _make_custom_list(
        session, parent, slug="top", max_items=3, sort_order=SortOrder.RATING_DESC
    )
    await init_items(session, cl)
    items = await serialize_custom_list(session, cl)
    assert [it.tmdb_id for it in items] == [1, 2, 3]


async def test_added_last_n_days_filters_by_added_at(session: AsyncSession) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    parent = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="WL",
        enabled=True,
    )
    session.add(parent)
    await session.flush()
    now = utcnow()
    added_by_tmdb = {
        1: now - timedelta(days=1),
        2: now - timedelta(days=5),
        3: now - timedelta(days=40),
    }
    for pos, (tmdb_id, added_at) in enumerate(added_by_tmdb.items()):
        session.add(
            Film(
                tmdb_id=tmdb_id,
                letterboxd_slug=f"f{tmdb_id}",
                title=f"Film {tmdb_id}",
                year=2020,
            )
        )
        session.add(ListItem(list_id=parent.id, tmdb_id=tmdb_id, position=pos, added_at=added_at))
    await session.flush()

    cl = await _make_custom_list(session, parent, slug="fresh", added_last_n_days=7)
    pool = await resolve_full_pool(session, cl)
    assert sorted(pool) == [1, 2]


async def test_rotate_swaps_oldest(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    cl = await _make_custom_list(
        session,
        parent,
        slug="rot",
        max_items=2,
        rotation_enabled=True,
        rotation_interval=timedelta(seconds=1),
        rotation_batch_size=1,
        last_rotated_at=utcnow() - timedelta(hours=1),
    )
    older = utcnow() - timedelta(days=2)
    newer = utcnow() - timedelta(hours=1)
    session.add_all(
        [
            CustomListItem(custom_list_id=cl.id, tmdb_id=1, position=0, served_since=older),
            CustomListItem(custom_list_id=cl.id, tmdb_id=2, position=1, served_since=newer),
        ]
    )
    await session.flush()

    rotated = await rotate(session, cl)
    assert rotated == 1
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    assert 1 not in tmdb_ids
    assert 2 in tmdb_ids
    assert len(tmdb_ids) == 2


async def test_rotate_leaves_positions_unique_and_consecutive(session: AsyncSession) -> None:
    """Tras varias rotaciones, ``position`` debe estar reindexada a [0..N-1]
    sin duplicados. Regresión: antes los items conservados mantenían su
    position original mientras los nuevos arrancaban en 0, colisionando."""
    _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5, 6, 7])
    cl = await _make_custom_list(
        session,
        parent,
        slug="rot-positions",
        max_items=3,
        rotation_enabled=True,
        rotation_interval=timedelta(seconds=1),
        rotation_batch_size=2,
        last_rotated_at=utcnow() - timedelta(hours=1),
    )
    await init_items(session, cl)

    # Forzar served_since más antiguo a los items iniciales y permitir rotación.
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    for it in items:
        it.served_since = utcnow() - timedelta(days=2)
    cl.last_rotated_at = utcnow() - timedelta(hours=1)
    await session.flush()

    rotated_first = await rotate(session, cl)
    assert rotated_first == 2

    # Reabrir ventana de rotación y rotar de nuevo.
    cl.last_rotated_at = utcnow() - timedelta(hours=1)
    items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    for it in items:
        it.served_since = utcnow() - timedelta(days=1)
    await session.flush()

    rotated_second = await rotate(session, cl)
    assert rotated_second >= 1

    final_items = (
        (
            await session.execute(
                select(CustomListItem).where(CustomListItem.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    positions = sorted(it.position for it in final_items)
    assert positions == list(range(len(positions)))


async def test_rotation_tick_handles_naive_datetime_from_db(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # SQLite descarta la tzinfo en columnas DateTime sin timezone=True, así
    # que `last_rotated_at` vuelve naive al releer; la aritmética con
    # `utcnow()` (aware) debe seguir funcionando.
    async with factory() as session:
        _, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
        cl = await _make_custom_list(
            session,
            parent,
            slug="naive-rot",
            max_items=2,
            rotation_enabled=True,
            rotation_interval=timedelta(seconds=1),
            rotation_batch_size=1,
            last_rotated_at=utcnow() - timedelta(hours=1),
        )
        older = utcnow() - timedelta(days=2)
        newer = utcnow() - timedelta(hours=1)
        session.add_all(
            [
                CustomListItem(custom_list_id=cl.id, tmdb_id=1, position=0, served_since=older),
                CustomListItem(custom_list_id=cl.id, tmdb_id=2, position=1, served_since=newer),
            ]
        )
        await session.commit()
        cl_id = cl.id

    async with factory() as session:
        reloaded = await session.get(CustomList, cl_id)
        assert reloaded is not None
        assert reloaded.last_rotated_at is not None
        assert reloaded.last_rotated_at.tzinfo is None

        rotated = await rotation_tick(session)
        assert rotated == 1


async def test_refresh_snapshot_skips_within_cooldown(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session,
        parent,
        slug="snap-skip",
        max_items=3,
        sort_order=SortOrder.LETTERBOXD,
        snapshot_interval=timedelta(days=7),
    )
    await init_items(session, cl)
    # init_items stampa last_snapshot_at = now → próximo refresh debe skipear.
    items_before = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListItem.tmdb_id)
                .where(CustomListItem.custom_list_id == cl.id)
                .order_by(CustomListItem.position)
            )
        ).all()
    ]

    refreshed = await refresh_snapshot(session, cl)
    assert refreshed == 0

    items_after = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListItem.tmdb_id)
                .where(CustomListItem.custom_list_id == cl.id)
                .order_by(CustomListItem.position)
            )
        ).all()
    ]
    assert items_before == items_after


async def test_refresh_snapshot_regenerates_when_cooldown_elapsed(
    session: AsyncSession,
) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30, 40, 50])
    cl = await _make_custom_list(
        session,
        parent,
        slug="snap-go",
        max_items=3,
        sort_order=SortOrder.LETTERBOXD,
        snapshot_interval=timedelta(hours=1),
    )
    await init_items(session, cl)
    # Forzar el último snapshot al pasado.
    cl.last_snapshot_at = utcnow() - timedelta(hours=2)
    await session.flush()

    refreshed = await refresh_snapshot(session, cl)
    assert refreshed == 3
    # Set congelado idéntico (mismo pool), pero last_snapshot_at se actualizó.
    assert cl.last_snapshot_at is not None
    assert cl.last_snapshot_at > utcnow() - timedelta(minutes=1)


async def test_refresh_snapshot_noop_when_interval_unset(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [1, 2, 3])
    cl = await _make_custom_list(session, parent, slug="no-snap", max_items=3)
    refreshed = await refresh_snapshot(session, cl)
    assert refreshed == 0


async def test_serialize_with_snapshot_mode_freezes_order(session: AsyncSession) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30])
    # Ratings: 30 más alto, luego 10, luego 20. Sin snapshot, RATING_DESC reordena.
    rating_by_tmdb = {10: 3.5, 20: 2.0, 30: 4.5}
    for tmdb_id, rating in rating_by_tmdb.items():
        film = await session.get(Film, tmdb_id)
        assert film is not None
        film.letterboxd_avg_rating = rating
    await session.flush()

    cl = await _make_custom_list(
        session,
        parent,
        slug="frozen",
        max_items=3,
        sort_order=SortOrder.RATING_DESC,
        snapshot_interval=timedelta(days=7),
    )
    # Persistir items en orden de inserción (10, 20, 30) — position 0..2.
    session.add_all(
        [
            CustomListItem(custom_list_id=cl.id, tmdb_id=10, position=0),
            CustomListItem(custom_list_id=cl.id, tmdb_id=20, position=1),
            CustomListItem(custom_list_id=cl.id, tmdb_id=30, position=2),
        ]
    )
    await session.flush()

    items = await serialize_custom_list(session, cl)
    # En modo snapshot, el orden viene de position — NO de rating actual.
    assert [it.tmdb_id for it in items] == [10, 20, 30]


async def test_serialize_without_snapshot_mode_reorders_by_rating(
    session: AsyncSession,
) -> None:
    _, parent = await _seed_user_list(session, [10, 20, 30])
    rating_by_tmdb = {10: 3.5, 20: 2.0, 30: 4.5}
    for tmdb_id, rating in rating_by_tmdb.items():
        film = await session.get(Film, tmdb_id)
        assert film is not None
        film.letterboxd_avg_rating = rating
    await session.flush()

    cl = await _make_custom_list(
        session,
        parent,
        slug="unfrozen",
        max_items=3,
        sort_order=SortOrder.RATING_DESC,
    )
    session.add_all(
        [
            CustomListItem(custom_list_id=cl.id, tmdb_id=10, position=0),
            CustomListItem(custom_list_id=cl.id, tmdb_id=20, position=1),
            CustomListItem(custom_list_id=cl.id, tmdb_id=30, position=2),
        ]
    )
    await session.flush()

    items = await serialize_custom_list(session, cl)
    # Sin snapshot, RATING_DESC reordena: 30 (4.5) → 10 (3.5) → 20 (2.0).
    assert [it.tmdb_id for it in items] == [30, 10, 20]
