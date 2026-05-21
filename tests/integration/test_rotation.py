from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    resolve_full_pool,
    rotate,
)


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


async def test_year_last_n_overrides_min_max_year(session: AsyncSession) -> None:
    current_year = utcnow().year
    _, parent = await _seed_user_list(session, [1], year=current_year)
    cl = await _make_custom_list(
        session, parent, slug="override", min_year=1900, max_year=1950, year_last_n=2
    )
    pool = await resolve_full_pool(session, cl)
    assert sorted(pool) == [1]


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
