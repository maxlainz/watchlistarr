"""Smoke test end-to-end de watchlistarr.

Arranca uvicorn contra una DB temporal con LETTERBOXD_OFFLINE=true, siembra dos
users de prueba, ejecuta GETs a los endpoints clave y valida el resultado.

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
    from watchlistarr.models.enums import SourceType, WatchedSource
    from watchlistarr.models.films import Film
    from watchlistarr.models.list_items import ListItem
    from watchlistarr.models.lists import List as ListModel
    from watchlistarr.models.sublist_items import SublistItem
    from watchlistarr.models.sublists import Sublist
    from watchlistarr.models.users import User
    from watchlistarr.models.watched_films import WatchedFilm

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
            )
            bob_wl = ListModel(
                user_id=bob.id,
                source_type=SourceType.WATCHLIST,
                slug="watchlist",
                name="WL",
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
            top = Sublist(
                user_id=alice.id,
                parent_list_id=alice_wl.id,
                slug="top",
                name="Top",
            )
            session.add(top)
            await session.flush()
            session.add_all(
                [
                    SublistItem(sublist_id=top.id, tmdb_id=10, position=0),
                    SublistItem(sublist_id=top.id, tmdb_id=20, position=1),
                ]
            )
            session.add(WatchedFilm(user_id=alice.id, tmdb_id=10, source=WatchedSource.RSS))
            await session.commit()
    finally:
        await engine.dispose()


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def _exercise(base_url: str) -> None:
    r = httpx.get(f"{base_url}/healthz")
    _assert(r.status_code == 200, f"/healthz != 200: {r.status_code}")

    r = httpx.get(f"{base_url}/")
    _assert(r.status_code == 200, f"/ != 200: {r.status_code}")
    _assert("Dashboard" in r.text, "dashboard sin marcador")

    r = httpx.get(f"{base_url}/alice/watchlist/")
    _assert(r.status_code == 200, "alice watchlist")
    body = r.json()
    _assert(isinstance(body, list) and len(body) == 3, f"alice watchlist len: {len(body)}")
    _assert(all(isinstance(i["tmdb_id"], int) for i in body), "tmdb_id no es int")

    r = httpx.get(f"{base_url}/all/watchlist/union/")
    _assert(r.status_code == 200 and len(r.json()) == 4, "union ≠ 4")

    r = httpx.get(f"{base_url}/all/watchlist/intersection/")
    _assert(r.status_code == 200 and len(r.json()) == 1, "intersection ≠ 1")

    r = httpx.get(f"{base_url}/all/watchlist/union-unwatched/")
    _assert(r.status_code == 200 and len(r.json()) == 3, "union-unwatched ≠ 3")

    r = httpx.get(f"{base_url}/alice/top/")
    _assert(r.status_code == 200 and len(r.json()) == 2, "alice/top ≠ 2")

    r = httpx.get(f"{base_url}/nobody/watchlist/")
    _assert(r.status_code == 404, "404 esperado para user inexistente")

    r = httpx.get(f"{base_url}/alice/watchlist/")
    etag = r.headers["etag"]
    r304 = httpx.get(f"{base_url}/alice/watchlist/", headers={"If-None-Match": etag})
    _assert(r304.status_code == 304, f"esperado 304, fue {r304.status_code}")


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
