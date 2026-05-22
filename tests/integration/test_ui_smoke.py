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
async def seeded_app(db_url: str, app: "FastAPI") -> "FastAPI":
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await _seed_alice_with_list(factory)
    await engine.dispose()
    return app


def test_spa_shell_renders(app: "FastAPI") -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Watchlistarr" in response.text
    assert "/static/src/app.jsx" in response.text


def test_bootstrap_endpoint(app: "FastAPI") -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert {"users", "customLists", "dashboard"}.issubset(body.keys())
    assert "stats" in body["dashboard"]


def test_users_list_endpoint(app: "FastAPI") -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/users")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_custom_lists_endpoint(app: "FastAPI") -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/custom-lists")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_activity_endpoint(app: "FastAPI") -> None:
    from datetime import UTC, datetime

    from watchlistarr.services.log_buffer import get_buffer

    # Inyectamos un log estructurado y otro legacy para verificar el shape de
    # ambos paths en la respuesta del endpoint.
    buf = get_buffer()
    buf.append_structured(
        level="INFO",
        event="watchlist.full_sync.start",
        fields={"user_id": 1, "list_id": 2},
        human_message="Watchlist full sync starting (user 1, list 2)",
        raw_message="raw",
        ts=datetime.now(tz=UTC),
        src="watchlist",
        exc_info=None,
    )
    buf.append("INFO", "alembic message", "migration")

    with TestClient(app) as client:
        response = client.get("/api/v1/activity")
    assert response.status_code == 200
    body = response.json()
    assert "lines" in body
    assert "latestSeq" in body
    structured = next(
        line for line in body["lines"] if line.get("event") == "watchlist.full_sync.start"
    )
    assert structured["fields"] == {"user_id": 1, "list_id": 2}
    assert structured["humanMessage"] == "Watchlist full sync starting (user 1, list 2)"
    assert structured["excInfo"] is None
    legacy = next(line for line in body["lines"] if line.get("src") == "migration")
    assert legacy["event"] is None
    assert legacy["fields"] == {}
    assert legacy["humanMessage"] == "alembic message"


def test_legacy_html_routes_gone(app: "FastAPI") -> None:
    with TestClient(app) as client:
        for path in ("/users", "/lists-view", "/custom-lists", "/activity"):
            assert client.get(path).status_code == 404


def test_user_detail_via_api(seeded_app: "FastAPI") -> None:
    with TestClient(seeded_app) as client:
        response = client.get("/api/v1/users")
    assert response.status_code == 200
    users = response.json()
    alice = next(u for u in users if u["username"] == "alice")
    assert alice["enabledCount"] == 2
    assert any(lst["name"] == "Watchlist" for lst in alice["lists"])
    assert any(lst["name"] == "Favs" for lst in alice["lists"])


def test_list_settings_via_api(seeded_app: "FastAPI") -> None:
    with TestClient(seeded_app) as client:
        users = client.get("/api/v1/users").json()
        alice = next(u for u in users if u["username"] == "alice")
        favs = next(lst for lst in alice["lists"] if lst["name"] == "Favs")

        resp = client.post(
            f"/api/v1/users/alice/lists/{favs['id']}/settings",
            json={"incrementalInterval": 6, "fullInterval": None, "flapConfirmScrapes": 5},
        )
        assert resp.status_code == 200

        after = client.get("/api/v1/users").json()
        alice2 = next(u for u in after if u["username"] == "alice")
        favs2 = next(lst for lst in alice2["lists"] if lst["name"] == "Favs")
        assert favs2["advanced"]["incrementalInterval"] == 6
        assert favs2["advanced"]["flapConfirmScrapes"] == 5


def test_watchlist_settings_via_api(seeded_app: "FastAPI") -> None:
    with TestClient(seeded_app) as client:
        users = client.get("/api/v1/users").json()
        alice = next(u for u in users if u["username"] == "alice")
        wl = next(lst for lst in alice["lists"] if lst["sourceType"] == "watchlist")

        resp = client.post(
            f"/api/v1/users/alice/lists/{wl['id']}/settings",
            json={"incrementalInterval": 2, "fullInterval": 48, "flapConfirmScrapes": None},
        )
        assert resp.status_code == 200

        after = client.get("/api/v1/users").json()
        alice2 = next(u for u in after if u["username"] == "alice")
        wl2 = next(lst for lst in alice2["lists"] if lst["sourceType"] == "watchlist")
        assert wl2["advanced"]["incrementalInterval"] == 2
        assert wl2["advanced"]["fullInterval"] == 48
