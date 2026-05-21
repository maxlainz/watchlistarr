from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from watchlistarr.models.custom_list_excluded_watchers import CustomListExcludedWatcher
from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import (
    CombinationOp,
    SortOrder,
    SourceRole,
    SourceType,
    WatchedSource,
)
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm

if TYPE_CHECKING:
    from fastapi import FastAPI


async def _seed_two_users(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        alice = User(letterboxd_username="alice")
        bob = User(letterboxd_username="bob")
        session.add_all([alice, bob])
        await session.flush()

        films = [
            Film(tmdb_id=10, letterboxd_slug="ten", title="Ten", year=2020, imdb_id="tt0000010"),
            Film(tmdb_id=20, letterboxd_slug="twenty", title="Twenty", year=2021),
            Film(
                tmdb_id=30, letterboxd_slug="thirty", title="Thirty", year=2022, imdb_id="tt0000030"
            ),
            Film(
                tmdb_id=40, letterboxd_slug="forty", title="Forty", year=2023, imdb_id="tt0000040"
            ),
        ]
        session.add_all(films)
        await session.flush()

        alice_wl = ListModel(
            user_id=alice.id,
            source_type=SourceType.WATCHLIST,
            slug="watchlist",
            name="WL",
            enabled=True,
        )
        bob_wl = ListModel(
            user_id=bob.id,
            source_type=SourceType.WATCHLIST,
            slug="watchlist",
            name="WL",
            enabled=True,
        )
        session.add_all([alice_wl, bob_wl])
        await session.flush()

        session.add_all(
            [
                ListItem(list_id=alice_wl.id, tmdb_id=10, position=0),
                ListItem(list_id=alice_wl.id, tmdb_id=20, position=1),
                ListItem(list_id=alice_wl.id, tmdb_id=30, position=2),
                ListItem(list_id=bob_wl.id, tmdb_id=30, position=0),
                ListItem(list_id=bob_wl.id, tmdb_id=40, position=1),
            ]
        )

        # Custom list: union of alice + bob watchlists
        union_cl = CustomList(
            slug="anyone",
            name="Anyone wants to watch",
            op=CombinationOp.UNION,
            sort_order=SortOrder.LETTERBOXD,
            rotation_enabled=False,
            rotation_batch_size=1,
            enabled=True,
        )
        session.add(union_cl)
        await session.flush()
        session.add_all(
            [
                CustomListSource(
                    custom_list_id=union_cl.id,
                    list_id=alice_wl.id,
                    role=SourceRole.INCLUDE,
                ),
                CustomListSource(
                    custom_list_id=union_cl.id,
                    list_id=bob_wl.id,
                    role=SourceRole.INCLUDE,
                ),
            ]
        )
        # init items manually with all 4 tmdb_ids
        session.add_all(
            [
                CustomListItem(custom_list_id=union_cl.id, tmdb_id=10, position=0),
                CustomListItem(custom_list_id=union_cl.id, tmdb_id=20, position=1),
                CustomListItem(custom_list_id=union_cl.id, tmdb_id=30, position=2),
                CustomListItem(custom_list_id=union_cl.id, tmdb_id=40, position=3),
            ]
        )

        # Custom list: intersection — only tmdb_id 30 is in both watchlists
        inter_cl = CustomList(
            slug="everyone",
            name="Everyone wants to watch",
            op=CombinationOp.INTERSECTION,
            sort_order=SortOrder.LETTERBOXD,
            rotation_enabled=False,
            rotation_batch_size=1,
            enabled=True,
        )
        session.add(inter_cl)
        await session.flush()
        session.add_all(
            [
                CustomListSource(
                    custom_list_id=inter_cl.id,
                    list_id=alice_wl.id,
                    role=SourceRole.INCLUDE,
                ),
                CustomListSource(
                    custom_list_id=inter_cl.id,
                    list_id=bob_wl.id,
                    role=SourceRole.INCLUDE,
                ),
            ]
        )
        session.add(CustomListItem(custom_list_id=inter_cl.id, tmdb_id=30, position=0))

        # Custom list: union minus already-watched by alice (tmdb_id 10)
        pending_cl = CustomList(
            slug="pending",
            name="Pending in common",
            op=CombinationOp.UNION,
            sort_order=SortOrder.LETTERBOXD,
            rotation_enabled=False,
            rotation_batch_size=1,
            enabled=True,
        )
        session.add(pending_cl)
        await session.flush()
        session.add_all(
            [
                CustomListSource(
                    custom_list_id=pending_cl.id,
                    list_id=alice_wl.id,
                    role=SourceRole.INCLUDE,
                ),
                CustomListSource(
                    custom_list_id=pending_cl.id,
                    list_id=bob_wl.id,
                    role=SourceRole.INCLUDE,
                ),
                CustomListExcludedWatcher(custom_list_id=pending_cl.id, user_id=alice.id),
            ]
        )
        session.add_all(
            [
                CustomListItem(custom_list_id=pending_cl.id, tmdb_id=20, position=0),
                CustomListItem(custom_list_id=pending_cl.id, tmdb_id=30, position=1),
                CustomListItem(custom_list_id=pending_cl.id, tmdb_id=40, position=2),
            ]
        )

        session.add(WatchedFilm(user_id=alice.id, tmdb_id=10, source=WatchedSource.RSS))
        await session.commit()


@pytest.fixture
async def seeded_app(db_url: str, app: FastAPI) -> FastAPI:
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _seed_two_users(factory)
    await engine.dispose()
    return app


def test_get_user_watchlist_returns_items(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/alice/watchlist/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body, list)
    tmdb_ids = sorted(item["tmdb_id"] for item in body)
    assert tmdb_ids == [10, 20, 30]
    by_tmdb = {item["tmdb_id"]: item for item in body}
    assert by_tmdb[10]["imdb_id"] == "tt0000010"
    assert by_tmdb[30]["imdb_id"] == "tt0000030"
    # Film 20 doesn't have imdb_id → field omitted via exclude_none.
    assert "imdb_id" not in by_tmdb[20]


def test_get_custom_list_union(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/lists/anyone/")
    assert response.status_code == 200
    tmdb_ids = sorted(item["tmdb_id"] for item in response.json())
    assert tmdb_ids == [10, 20, 30, 40]


def test_get_custom_list_intersection(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/lists/everyone/")
    assert response.status_code == 200
    tmdb_ids = [item["tmdb_id"] for item in response.json()]
    assert tmdb_ids == [30]


def test_get_custom_list_excluding_watched(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/lists/pending/")
    assert response.status_code == 200
    tmdb_ids = sorted(item["tmdb_id"] for item in response.json())
    assert tmdb_ids == [20, 30, 40]


def test_404_when_user_does_not_exist(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/nobody/watchlist/")
    assert response.status_code == 404


def test_404_when_slug_does_not_exist(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/alice/inexistente/")
    assert response.status_code == 404


def test_404_when_custom_list_unknown(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/lists/nope/")
    assert response.status_code == 404


def test_old_combined_urls_gone(seeded_app: FastAPI) -> None:
    """The old /all/watchlist/<kind>/ endpoints are removed."""
    with TestClient(seeded_app) as client:
        for path in (
            "/all/watchlist/union/",
            "/all/watchlist/intersection/",
            "/all/watchlist/union-unwatched/",
        ):
            response = client.get(path)
            assert response.status_code == 404


def test_reserved_username_returns_404(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/api/something/")
    assert response.status_code == 404


def test_etag_returns_304_on_match(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        first = client.get("/alice/watchlist/")
        etag = first.headers["etag"]
        second = client.get("/alice/watchlist/", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag
