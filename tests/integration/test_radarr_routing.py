from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from watchlistarr.models.enums import SourceType, WatchedSource
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.sublist_items import SublistItem
from watchlistarr.models.sublists import Sublist
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
            Film(tmdb_id=10, letterboxd_slug="ten", title="Ten", year=2020),
            Film(tmdb_id=20, letterboxd_slug="twenty", title="Twenty", year=2021),
            Film(tmdb_id=30, letterboxd_slug="thirty", title="Thirty", year=2022),
            Film(tmdb_id=40, letterboxd_slug="forty", title="Forty", year=2023),
        ]
        session.add_all(films)
        await session.flush()

        alice_wl = ListModel(
            user_id=alice.id, source_type=SourceType.WATCHLIST, slug="watchlist", name="WL"
        )
        bob_wl = ListModel(
            user_id=bob.id, source_type=SourceType.WATCHLIST, slug="watchlist", name="WL"
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

        alice_top = Sublist(
            user_id=alice.id,
            parent_list_id=alice_wl.id,
            slug="top",
            name="Top",
        )
        session.add(alice_top)
        await session.flush()
        session.add_all(
            [
                SublistItem(sublist_id=alice_top.id, tmdb_id=10, position=0),
                SublistItem(sublist_id=alice_top.id, tmdb_id=20, position=1),
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
    assert all(isinstance(item["tmdb_id"], int) for item in body)


def test_get_combined_union(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/all/watchlist/union/")
    assert response.status_code == 200
    tmdb_ids = sorted(item["tmdb_id"] for item in response.json())
    assert tmdb_ids == [10, 20, 30, 40]


def test_get_combined_intersection(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/all/watchlist/intersection/")
    assert response.status_code == 200
    tmdb_ids = [item["tmdb_id"] for item in response.json()]
    assert tmdb_ids == [30]


def test_get_combined_union_unwatched(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/all/watchlist/union-unwatched/")
    assert response.status_code == 200
    tmdb_ids = sorted(item["tmdb_id"] for item in response.json())
    assert tmdb_ids == [20, 30, 40]


def test_get_user_sublist(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/alice/top/")
    assert response.status_code == 200
    tmdb_ids = sorted(item["tmdb_id"] for item in response.json())
    assert tmdb_ids == [10, 20]


def test_404_when_user_does_not_exist(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/nobody/watchlist/")
    assert response.status_code == 404


def test_404_when_slug_does_not_exist(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/alice/inexistente/")
    assert response.status_code == 404


def test_404_when_combo_unknown(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/all/watchlist/notakind/")
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
