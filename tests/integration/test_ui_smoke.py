from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User

if TYPE_CHECKING:
    from fastapi import FastAPI


async def _seed_alice_with_list(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        alice = User(letterboxd_username="alice")
        session.add(alice)
        await session.flush()
        session.add_all(
            [
                ListModel(
                    user_id=alice.id,
                    source_type=SourceType.WATCHLIST,
                    slug="watchlist",
                    name="WL",
                ),
                ListModel(
                    user_id=alice.id,
                    source_type=SourceType.LIST,
                    letterboxd_list_id="42",
                    slug="favs",
                    name="Favs",
                ),
            ]
        )
        await session.commit()


@pytest.fixture
async def seeded_app(db_url: str, app: FastAPI) -> FastAPI:
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _seed_alice_with_list(factory)
    await engine.dispose()
    return app


def test_dashboard_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_users_list_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/users")
    assert response.status_code == 200
    assert "Users" in response.text


def test_combined_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/combined")
    assert response.status_code == 200
    assert "Combinadas" in response.text


def test_settings_route_gone(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/settings")
    assert response.status_code == 404


def test_activity_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/activity")
    assert response.status_code == 200
    assert "Actividad" in response.text


def test_endpoints_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/endpoints")
    assert response.status_code == 200
    assert "Endpoints" in response.text


def test_combined_new_sublist_form_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/combined/sublists/new")
    assert response.status_code == 200
    assert "Nueva sublista combinada" in response.text


def test_user_intervals_get_and_post(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        page = client.get("/users/alice/intervals")
        assert page.status_code == 200
        assert "rss_interval" in page.text
        assert "(default)" in page.text

        # POST con un override y dejar el resto en blanco → resto vuelve a NULL.
        resp = client.post(
            "/users/alice/intervals",
            data={
                "rss_interval": "300",
                "watchlist_incremental_interval": "",
                "watchlist_full_interval": "",
                "films_backstop_interval": "",
                "discovery_interval": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        after = client.get("/users/alice/intervals")
        assert 'value="300"' in after.text


def test_user_intervals_404_unknown_user(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        assert client.get("/users/nobody/intervals").status_code == 404


def test_list_settings_get_and_post(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        page = client.get("/users/alice/lists/favs/settings")
        assert page.status_code == 200
        assert "lists_incremental_interval" in page.text
        assert "flap_confirm_scrapes" in page.text

        resp = client.post(
            "/users/alice/lists/favs/settings",
            data={
                "lists_incremental_interval": "120",
                "lists_full_interval": "",
                "flap_confirm_scrapes": "5",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        after = client.get("/users/alice/lists/favs/settings")
        assert 'value="120"' in after.text
        assert 'value="5"' in after.text


def test_list_settings_404_unknown_list(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        assert client.get("/users/alice/lists/no-such/settings").status_code == 404
