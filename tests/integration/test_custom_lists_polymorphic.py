from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import CombinationOp, SortOrder, SourceRole, SourceType
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.custom_lists import (
    detect_cycle,
    eligible_pool,
    init_items,
    resolve_universe,
)


async def _seed_user_list(
    session: AsyncSession,
    username: str,
    tmdb_ids: list[int],
    slug: str = "watchlist",
    year: int = 2020,
) -> tuple[User, ListModel]:
    user = User(letterboxd_username=username)
    session.add(user)
    await session.flush()
    lst = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST if slug == "watchlist" else SourceType.LIST,
        slug=slug,
        name=slug,
        enabled=True,
    )
    session.add(lst)
    await session.flush()
    for pos, tmdb_id in enumerate(tmdb_ids):
        existing = await session.get(Film, tmdb_id)
        if existing is None:
            session.add(
                Film(
                    tmdb_id=tmdb_id,
                    letterboxd_slug=f"f{tmdb_id}",
                    title=f"Film {tmdb_id}",
                    year=year,
                )
            )
        session.add(ListItem(list_id=lst.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()
    return user, lst


async def _make_cl(
    session: AsyncSession,
    slug: str,
    *,
    list_includes: list[int] | None = None,
    cl_includes: list[int] | None = None,
    list_subtracts: list[int] | None = None,
    cl_subtracts: list[int] | None = None,
    op: CombinationOp = CombinationOp.UNION,
    max_items: int | None = None,
    sort_order: SortOrder = SortOrder.LETTERBOXD,
) -> CustomList:
    cl = CustomList(
        slug=slug,
        name=slug,
        op=op,
        sort_order=sort_order,
        max_items=max_items,
        rotation_enabled=False,
        rotation_batch_size=1,
        enabled=True,
    )
    session.add(cl)
    await session.flush()
    for lid in list_includes or []:
        session.add(CustomListSource(custom_list_id=cl.id, list_id=lid, role=SourceRole.INCLUDE))
    for cid in cl_includes or []:
        session.add(
            CustomListSource(
                custom_list_id=cl.id, source_custom_list_id=cid, role=SourceRole.INCLUDE
            )
        )
    for lid in list_subtracts or []:
        session.add(CustomListSource(custom_list_id=cl.id, list_id=lid, role=SourceRole.SUBTRACT))
    for cid in cl_subtracts or []:
        session.add(
            CustomListSource(
                custom_list_id=cl.id, source_custom_list_id=cid, role=SourceRole.SUBTRACT
            )
        )
    await session.flush()
    return cl


async def test_custom_list_as_include_reads_served_items(session: AsyncSession) -> None:
    _, lst = await _seed_user_list(session, "alice", [1, 2, 3, 4, 5])
    b = await _make_cl(session, "b", list_includes=[lst.id], max_items=3)
    await init_items(session, b)
    # B sirve 3 items deterministas (LETTERBOXD order): 1, 2, 3.
    b_served = sorted(
        row[0]
        for row in (
            await session.execute(
                select(CustomListItem.tmdb_id).where(CustomListItem.custom_list_id == b.id)
            )
        ).all()
    )
    assert b_served == [1, 2, 3]

    a = await _make_cl(session, "a", cl_includes=[b.id])
    universe = await resolve_universe(session, a)
    assert universe == {1, 2, 3}


async def test_intersection_mixes_list_and_custom_list(session: AsyncSession) -> None:
    _, lst_a = await _seed_user_list(session, "alice", [1, 2, 3, 4, 5])
    _, lst_b = await _seed_user_list(session, "bob", [3, 4, 5, 6, 7], slug="watchlist")
    b = await _make_cl(session, "b", list_includes=[lst_b.id], max_items=5)
    await init_items(session, b)
    # B sirve {3,4,5,6,7}.
    a = await _make_cl(
        session,
        "a-intersect",
        list_includes=[lst_a.id],
        cl_includes=[b.id],
        op=CombinationOp.INTERSECTION,
    )
    universe = await resolve_universe(session, a)
    assert universe == {3, 4, 5}


async def test_custom_list_as_subtract(session: AsyncSession) -> None:
    _, lst_a = await _seed_user_list(session, "alice", [1, 2, 3, 4, 5])
    _, lst_b = await _seed_user_list(session, "bob", [4, 5], slug="watchlist")
    b = await _make_cl(session, "b", list_includes=[lst_b.id], max_items=5)
    await init_items(session, b)
    a = await _make_cl(session, "a-sub", list_includes=[lst_a.id], cl_subtracts=[b.id])
    universe = await resolve_universe(session, a)
    assert universe == {1, 2, 3}


async def test_a_picks_up_b_changes_on_next_recalculate(session: AsyncSession) -> None:
    """B regenera items (cambio en max_items / pool) → A.recalculate ve los nuevos."""
    _, lst = await _seed_user_list(session, "alice", [1, 2, 3, 4, 5])
    b = await _make_cl(session, "b", list_includes=[lst.id], max_items=2)
    await init_items(session, b)
    a = await _make_cl(session, "a", cl_includes=[b.id])
    pool_v1 = sorted(await eligible_pool(session, a))
    assert pool_v1 == [1, 2]  # LETTERBOXD-sorted top-2 de B

    # Cambia B: subir max_items y regenerar items (simulamos snapshot refresh).
    await session.execute(ListItem.__table__.delete().where(ListItem.list_id == lst.id))
    for pos, tmdb_id in enumerate([1, 2, 3]):
        session.add(ListItem(list_id=lst.id, tmdb_id=tmdb_id, position=pos))
    await session.flush()

    await session.execute(
        CustomListItem.__table__.delete().where(CustomListItem.custom_list_id == b.id)
    )
    await session.flush()
    b.max_items = 3
    await session.flush()
    await init_items(session, b)

    pool_v2 = sorted(await eligible_pool(session, a))
    assert pool_v2 == [1, 2, 3]


async def test_detect_cycle_self_reference(session: AsyncSession) -> None:
    _, lst = await _seed_user_list(session, "alice", [1, 2])
    a = await _make_cl(session, "a", list_includes=[lst.id])
    closer = await detect_cycle(session, a.id, [a.id])
    assert closer == a.id


async def test_detect_cycle_two_hops(session: AsyncSession) -> None:
    _, lst = await _seed_user_list(session, "alice", [1, 2])
    a = await _make_cl(session, "a", list_includes=[lst.id])
    b = await _make_cl(session, "b", cl_includes=[a.id])
    # Si A intenta incluir B, B ya alcanza A → ciclo.
    closer = await detect_cycle(session, a.id, [b.id])
    assert closer == a.id


async def test_detect_cycle_three_hops(session: AsyncSession) -> None:
    _, lst = await _seed_user_list(session, "alice", [1, 2])
    a = await _make_cl(session, "a", list_includes=[lst.id])
    b = await _make_cl(session, "b", cl_includes=[a.id])
    c = await _make_cl(session, "c", cl_includes=[b.id])
    closer = await detect_cycle(session, a.id, [c.id])
    assert closer == a.id


async def test_detect_cycle_branches_without_loop_ok(session: AsyncSession) -> None:
    _, lst = await _seed_user_list(session, "alice", [1, 2])
    b = await _make_cl(session, "b", list_includes=[lst.id])
    c = await _make_cl(session, "c", list_includes=[lst.id])
    a = await _make_cl(session, "a", list_includes=[lst.id])
    closer = await detect_cycle(session, a.id, [b.id, c.id])
    assert closer is None


async def test_api_rejects_self_reference(app, factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        _, lst = await _seed_user_list(session, "alice", [1, 2, 3])
        list_id = lst.id
        await session.commit()

    with TestClient(app) as client:
        create = client.post(
            "/api/v1/custom-lists",
            json={
                "slug": "loop",
                "name": "Loop",
                "op": "union",
                "sources": [{"listId": list_id, "role": "include"}],
            },
        )
        assert create.status_code == 201, create.text
        cl_id = create.json()["id"]

        update = client.put(
            "/api/v1/custom-lists/loop",
            json={
                "name": "Loop",
                "op": "union",
                "sources": [{"customListId": cl_id, "role": "include"}],
            },
        )
        assert update.status_code == 400
        assert "cycle" in update.json()["detail"]


async def test_api_rejects_cycle_via_two_hops(
    app, factory: async_sessionmaker[AsyncSession]
) -> None:
    async with factory() as session:
        _, lst = await _seed_user_list(session, "alice", [1, 2, 3])
        list_id = lst.id
        await session.commit()

    with TestClient(app) as client:
        create_a = client.post(
            "/api/v1/custom-lists",
            json={
                "slug": "a",
                "name": "A",
                "op": "union",
                "sources": [{"listId": list_id, "role": "include"}],
            },
        )
        assert create_a.status_code == 201, create_a.text
        a_id = create_a.json()["id"]

        create_b = client.post(
            "/api/v1/custom-lists",
            json={
                "slug": "b",
                "name": "B",
                "op": "union",
                "sources": [{"customListId": a_id, "role": "include"}],
            },
        )
        assert create_b.status_code == 201, create_b.text

        cycle = client.put(
            "/api/v1/custom-lists/a",
            json={
                "name": "A",
                "op": "union",
                "sources": [{"customListId": create_b.json()["id"], "role": "include"}],
            },
        )
        assert cycle.status_code == 400
        assert "cycle" in cycle.json()["detail"]
