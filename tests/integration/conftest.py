from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from watchlistarr.config import Settings
from watchlistarr.services.letterboxd.client import LetterboxdClient

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def letterboxd_settings() -> Settings:
    return Settings(letterboxd_offline=False, user_agent="watchlistarr-tests/0.1.0")


@pytest.fixture
async def letterboxd_client(letterboxd_settings: Settings) -> AsyncIterator[LetterboxdClient]:
    client = LetterboxdClient(letterboxd_settings, min_interval_seconds=0)
    try:
        yield client
    finally:
        await client.aclose()
