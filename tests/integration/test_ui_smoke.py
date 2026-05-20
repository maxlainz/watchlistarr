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
                    enabled=True,
                ),
                ListModel(
                    user_id=alice.id,
                    source_type=SourceType.LIST,
                    letterboxd_list_id="42",
                    slug="favs",
                    name="Favs",
                    enabled=True,
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


def test_lists_view_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/lists-view")
    assert response.status_code == 200
    assert "Lists" in response.text


def test_custom_lists_index_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/custom-lists")
    assert response.status_code == 200
    assert "Custom Lists" in response.text


def test_custom_lists_new_form_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/custom-lists/new")
    assert response.status_code == 200
    assert "New custom list" in response.text


def test_activity_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/activity")
    assert response.status_code == 200
    assert "Activity" in response.text


def test_settings_route_gone(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/settings")
    assert response.status_code == 404


def test_endpoints_route_gone(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/endpoints")
    assert response.status_code == 404


def test_combined_route_gone(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/combined")
    assert response.status_code == 404


def test_user_detail_renders_with_lists(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/users/alice")
    assert response.status_code == 200
    assert "Discovered lists" in response.text
    # Watchlist and Favs both appear in the discovered table
    assert "Watchlist" in response.text
    assert "Favs" in response.text
    # Advanced intervals collapsible is present
    assert "Advanced" in response.text


def test_user_intervals_post(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
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

        after = client.get("/users/alice")
        assert 'value="300"' in after.text


def test_list_settings_post_via_lists_view(seeded_app: FastAPI) -> None:
    with TestClient(seeded_app) as client:
        resp = client.post(
            "/lists-view/alice/favs/settings",
            data={
                "lists_incremental_interval": "120",
                "lists_full_interval": "",
                "flap_confirm_scrapes": "5",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        after = client.get("/lists-view")
        assert 'value="120"' in after.text
        assert 'value="5"' in after.text
