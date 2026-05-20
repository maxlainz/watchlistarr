from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from watchlistarr.models import (
    CombinationOp,
    CustomList,
    CustomListSource,
    Film,
    List,
    ListItem,
    SortOrder,
    SourceRole,
    SourceType,
    SyncStatus,
    User,
)


async def test_all_tables_created(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda c: sorted(inspect(c).get_table_names()))
    expected = {
        "alembic_version",
        "custom_list_excluded_watchers",
        "custom_list_items",
        "custom_list_sources",
        "custom_lists",
        "films",
        "list_items",
        "lists",
        "scrape_runs",
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


async def test_custom_list_with_source(session: AsyncSession) -> None:
    user = User(letterboxd_username="bob")
    session.add(user)
    await session.flush()
    parent = List(
        user_id=user.id, source_type=SourceType.WATCHLIST, slug="watchlist", name="WL"
    )
    session.add(parent)
    await session.flush()

    cl = CustomList(
        slug="top",
        name="Top picks",
        op=CombinationOp.UNION,
        sort_order=SortOrder.LETTERBOXD,
        rotation_enabled=False,
        rotation_batch_size=1,
        enabled=True,
    )
    session.add(cl)
    await session.flush()
    session.add(
        CustomListSource(custom_list_id=cl.id, list_id=parent.id, role=SourceRole.INCLUDE)
    )
    await session.commit()
    assert cl.id is not None
