from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from watchlistarr.models import (
    CombinedKind,
    Film,
    List,
    ListItem,
    SortOrder,
    SourceType,
    Sublist,
    SyncStatus,
    User,
)


async def test_all_tables_created(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda c: sorted(inspect(c).get_table_names()))
    expected = {
        "alembic_version",
        "films",
        "list_items",
        "lists",
        "scrape_runs",
        "sublist_items",
        "sublists",
        "users",
        "viewing_logs",
        "watched_films",
    }
    assert expected.issubset(set(tables))


async def test_user_list_film_crud(session: AsyncSession) -> None:
    user = User(letterboxd_username="alice", display_name="Alice")
    session.add(user)
    await session.flush()

    watchlist = List(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="Watchlist",
    )
    session.add(watchlist)
    await session.flush()

    film = Film(tmdb_id=496243, letterboxd_slug="parasite-2019", title="Parasite", year=2019)
    session.add(film)
    await session.flush()

    item = ListItem(list_id=watchlist.id, tmdb_id=film.tmdb_id, position=0)
    session.add(item)
    await session.commit()

    found = (
        await session.execute(select(User).where(User.letterboxd_username == "alice"))
    ).scalar_one()
    assert found.id == user.id
    assert watchlist.last_sync_status is SyncStatus.NEVER


async def test_sublist_check_constraint_user_only(session: AsyncSession) -> None:
    user = User(letterboxd_username="bob")
    session.add(user)
    await session.flush()
    parent = List(user_id=user.id, source_type=SourceType.WATCHLIST, slug="watchlist", name="WL")
    session.add(parent)
    await session.flush()

    sub = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug="top",
        name="Top",
        sort_order=SortOrder.LETTERBOXD,
    )
    session.add(sub)
    await session.commit()
    assert sub.id is not None


async def test_sublist_check_constraint_rejects_both_parents(session: AsyncSession) -> None:
    user = User(letterboxd_username="carol")
    session.add(user)
    await session.flush()
    parent = List(user_id=user.id, source_type=SourceType.WATCHLIST, slug="watchlist", name="WL")
    session.add(parent)
    await session.flush()

    invalid = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        parent_combined_kind=CombinedKind.UNION,
        slug="mixed",
        name="Mixed",
    )
    session.add(invalid)
    with pytest.raises(IntegrityError):
        await session.commit()
