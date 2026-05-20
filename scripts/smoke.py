"""Smoke test end-to-end de watchlistarr.

Arranca uvicorn contra una DB temporal con LETTERBOXD_OFFLINE=true, siembra
users + listas + custom list de prueba, y valida que la SPA shell, el JSON API
y los endpoints Radarr respondan lo esperado.

Uso:
    uv run python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = ROOT / "alembic.ini"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_healthz(base_url: str, timeout: float = 15.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            r = httpx.get(f"{base_url}/healthz", timeout=2.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"healthz no respondió en {timeout}s")


async def _seed(db_url: str) -> None:
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
    from watchlistarr.services.custom_lists import init_items

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            alice = User(letterboxd_username="alice")
            bob = User(letterboxd_username="bob")
            session.add_all([alice, bob])
            await session.flush()
            session.add_all(
                [
                    Film(tmdb_id=10, letterboxd_slug="ten", title="Ten", year=2020),
                    Film(tmdb_id=20, letterboxd_slug="twenty", title="Twenty", year=2021),
                    Film(tmdb_id=30, letterboxd_slug="thirty", title="Thirty", year=2022),
                    Film(tmdb_id=40, letterboxd_slug="forty", title="Forty", year=2023),
                ]
            )
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
            session.add(WatchedFilm(user_id=alice.id, tmdb_id=10, source=WatchedSource.RSS))
            await session.flush()

            house = CustomList(
                slug="house",
                name="House watchlist",
                op=CombinationOp.UNION,
                sort_order=SortOrder.LETTERBOXD,
                enabled=True,
            )
            session.add(house)
            await session.flush()
            session.add_all(
                [
                    CustomListSource(
                        custom_list_id=house.id,
                        list_id=alice_wl.id,
                        role=SourceRole.INCLUDE,
                    ),
                    CustomListSource(
                        custom_list_id=house.id,
                        list_id=bob_wl.id,
                        role=SourceRole.INCLUDE,
                    ),
                ]
            )
            await session.flush()
            await init_items(session, house)
            await session.commit()
    finally:
        await engine.dispose()


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def _exercise(base_url: str) -> None:
    r = httpx.get(f"{base_url}/healthz")
    _assert(r.status_code == 200, f"/healthz != 200: {r.status_code}")

    # SPA shell: HTML estático, los componentes los renderiza React en el cliente.
    r = httpx.get(f"{base_url}/")
    _assert(r.status_code == 200, f"/ != 200: {r.status_code}")
    _assert("Watchlistarr" in r.text, "shell sin <title>")
    _assert('id="root"' in r.text, "shell sin mountpoint")

    for path in (
        "/static/styles.css",
        "/static/vendor/react.min.js",
        "/static/vendor/geist/geist.css",
    ):
        rr = httpx.get(f"{base_url}{path}")
        _assert(rr.status_code == 200, f"{path} != 200: {rr.status_code}")

    # JSON API bootstrap.
    r = httpx.get(f"{base_url}/api/v1/bootstrap")
    _assert(r.status_code == 200, f"bootstrap != 200: {r.status_code}")
    body = r.json()
    for key in ("users", "customLists", "dashboard"):
        _assert(key in body, f"bootstrap missing {key}")
    usernames = {u["username"] for u in body["users"]}
    _assert(usernames == {"alice", "bob"}, f"users inesperados: {usernames}")
    for u in body["users"]:
        _assert("discoveryRunning" in u, f"user {u['username']} sin discoveryRunning")
        _assert("syncingListIds" in u, f"user {u['username']} sin syncingListIds")
        _assert(u["discoveryRunning"] is False, f"user {u['username']} discoveryRunning != False")
        _assert(u["syncingListIds"] == [], f"user {u['username']} syncingListIds no vacío")
    _assert(
        any(cl["slug"] == "house" for cl in body["customLists"]),
        "house custom list no aparece",
    )

    r = httpx.get(f"{base_url}/api/v1/activity?since=0")
    _assert(r.status_code == 200, f"activity != 200: {r.status_code}")
    payload = r.json()
    _assert("lines" in payload and "latestSeq" in payload, "activity payload incompleto")

    # Radarr endpoints (DB-authoritative).
    r = httpx.get(f"{base_url}/alice/watchlist/")
    _assert(r.status_code == 200, "alice watchlist != 200")
    items = r.json()
    _assert(isinstance(items, list) and len(items) == 3, f"alice watchlist len: {len(items)}")
    _assert(all(isinstance(i["tmdb_id"], int) for i in items), "tmdb_id no es int")

    r = httpx.get(f"{base_url}/lists/house/")
    _assert(r.status_code == 200, "house custom list != 200")
    _assert(len(r.json()) == 4, f"house items != 4: {len(r.json())}")

    r = httpx.get(f"{base_url}/nobody/watchlist/")
    _assert(r.status_code == 404, "404 esperado para user inexistente")

    # ETag / 304.
    r = httpx.get(f"{base_url}/alice/watchlist/")
    etag = r.headers["etag"]
    r304 = httpx.get(f"{base_url}/alice/watchlist/", headers={"If-None-Match": etag})
    _assert(r304.status_code == 304, f"esperado 304, fue {r304.status_code}")

    # Las viejas rutas HTML server-rendered ya no existen.
    for legacy in ("/users", "/lists-view", "/custom-lists", "/activity"):
        rr = httpx.get(f"{base_url}{legacy}")
        _assert(rr.status_code == 404, f"{legacy} debería ser 404, fue {rr.status_code}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="watchlistarr-smoke-") as tmpdir:
        db_path = Path(tmpdir) / "smoke.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env["DATABASE_URL"] = db_url
        env["LETTERBOXD_OFFLINE"] = "true"
        env["LOG_LEVEL"] = "warning"
        env["HTTP_PORT"] = str(port)

        cfg = AlembicConfig(str(ALEMBIC_INI))
        os.environ["DATABASE_URL"] = db_url
        try:
            command.upgrade(cfg, "head")
        finally:
            os.environ.pop("DATABASE_URL", None)

        asyncio.run(_seed(db_url))

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "watchlistarr.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            env=env,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_healthz(base_url)
            _exercise(base_url)
            print(f"SMOKE OK: {base_url}")
            return 0
        except Exception as exc:
            print(f"SMOKE FAIL: {exc}", file=sys.stderr)
            return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


if __name__ == "__main__":
    sys.exit(main())
