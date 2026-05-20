from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import SourceType
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.sublist_items import SublistItem
from watchlistarr.models.sublists import Sublist
from watchlistarr.models.users import User
from watchlistarr.services.rotation import (
    eligible_pool,
    init_sublist_items,
    recalculate_sublist,
    rotate_sublist,
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


async def test_init_sublist_items_picks_random_subset(session: AsyncSession) -> None:
    user, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    sublist = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug="top",
        name="Top",
        max_items=3,
    )
    session.add(sublist)
    await session.flush()

    count = await init_sublist_items(session, sublist)
    assert count == 3
    items = (
        (await session.execute(select(SublistItem).where(SublistItem.sublist_id == sublist.id)))
        .scalars()
        .all()
    )
    assert len(list(items)) == 3


async def test_eligible_pool_excludes_already_served(session: AsyncSession) -> None:
    user, parent = await _seed_user_list(session, [1, 2, 3])
    sublist = Sublist(user_id=user.id, parent_list_id=parent.id, slug="s", name="S", max_items=2)
    session.add(sublist)
    await session.flush()
    session.add(SublistItem(sublist_id=sublist.id, tmdb_id=1, position=0))
    await session.flush()

    pool = await eligible_pool(session, sublist)
    assert sorted(pool) == [2, 3]


async def test_recalculate_sublist_drops_invalid_and_refills(session: AsyncSession) -> None:
    user, parent = await _seed_user_list(session, [1, 2, 3, 4], year=2010)
    # Cambiar el year de uno para que filtre.
    film2 = await session.get(Film, 2)
    assert film2 is not None
    film2.year = 1990
    sublist = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug="modern",
        name="Modern",
        max_items=3,
        min_year=2000,
    )
    session.add(sublist)
    await session.flush()
    session.add_all(
        [
            SublistItem(sublist_id=sublist.id, tmdb_id=1, position=0),
            SublistItem(sublist_id=sublist.id, tmdb_id=2, position=1),  # ya no califica
        ]
    )
    await session.flush()

    await recalculate_sublist(session, sublist)
    items = (
        (await session.execute(select(SublistItem).where(SublistItem.sublist_id == sublist.id)))
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    assert 2 not in tmdb_ids
    assert len(tmdb_ids) == 3  # rellenado hasta max_items con pool válido


async def test_rotate_sublist_respects_interval(session: AsyncSession) -> None:
    user, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    sublist = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug="rot",
        name="Rot",
        max_items=2,
        rotation_enabled=True,
        rotation_interval=timedelta(days=7),
        rotation_batch_size=1,
        last_rotated_at=utcnow(),
    )
    session.add(sublist)
    await session.flush()
    session.add_all(
        [
            SublistItem(sublist_id=sublist.id, tmdb_id=1, position=0),
            SublistItem(sublist_id=sublist.id, tmdb_id=2, position=1),
        ]
    )
    await session.flush()

    rotated = await rotate_sublist(session, sublist)
    assert rotated == 0


async def test_rotate_sublist_swaps_oldest(session: AsyncSession) -> None:
    user, parent = await _seed_user_list(session, [1, 2, 3, 4, 5])
    sublist = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug="rot",
        name="Rot",
        max_items=2,
        rotation_enabled=True,
        rotation_interval=timedelta(seconds=1),
        rotation_batch_size=1,
        last_rotated_at=utcnow() - timedelta(hours=1),
    )
    session.add(sublist)
    await session.flush()
    older = utcnow() - timedelta(days=2)
    newer = utcnow() - timedelta(hours=1)
    session.add_all(
        [
            SublistItem(sublist_id=sublist.id, tmdb_id=1, position=0, served_since=older),
            SublistItem(sublist_id=sublist.id, tmdb_id=2, position=1, served_since=newer),
        ]
    )
    await session.flush()

    rotated = await rotate_sublist(session, sublist)
    assert rotated == 1
    items = (
        (await session.execute(select(SublistItem).where(SublistItem.sublist_id == sublist.id)))
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    # El más viejo (1) sale; el más nuevo (2) queda; entra uno random del pool {3,4,5}.
    assert 1 not in tmdb_ids
    assert 2 in tmdb_ids
    assert len(tmdb_ids) == 2
