from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from watchlistarr.config import get_settings
from watchlistarr.db import dispose_engine, init_engine

if TYPE_CHECKING:
    from fastapi import FastAPI

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@pytest.fixture
def db_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LETTERBOXD_OFFLINE", "true")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    get_settings.cache_clear()
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    command.upgrade(cfg, "head")
    yield url
    get_settings.cache_clear()


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = init_engine(db_url)
    yield eng
    await dispose_engine()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s


@pytest.fixture
def app(db_url: str) -> FastAPI:
    from watchlistarr.main import create_app

    return create_app()
