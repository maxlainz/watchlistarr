from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from watchlistarr.config import Settings
from watchlistarr.services.letterboxd.client import (
    LetterboxdClient,
    LetterboxdOfflineError,
)


def _make_settings(*, offline: bool = False) -> Settings:
    return Settings(letterboxd_offline=offline)


@respx.mock
async def test_get_returns_response() -> None:
    settings = _make_settings()
    respx.get("https://letterboxd.com/maxlainz/").mock(return_value=httpx.Response(200, text="ok"))
    async with LetterboxdClient(settings) as client:
        response = await client.get("/maxlainz/")
    assert response.status_code == 200
    assert response.text == "ok"


async def test_get_offline_raises() -> None:
    settings = _make_settings(offline=True)
    async with LetterboxdClient(settings) as client:
        with pytest.raises(LetterboxdOfflineError):
            await client.get("/maxlainz/")


@respx.mock
async def test_get_403_does_not_retry() -> None:
    settings = _make_settings()
    route = respx.get("https://letterboxd.com/forbidden/").mock(
        return_value=httpx.Response(403, text="nope")
    )
    async with LetterboxdClient(settings) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/forbidden/")
    assert route.call_count == 1


@respx.mock
async def test_get_5xx_retries_then_succeeds() -> None:
    settings = _make_settings()
    route = respx.get("https://letterboxd.com/flaky/").mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, text="ok"),
        ]
    )

    # Patch sleep para que el backoff no demore.
    async def _no_sleep(_seconds: float) -> None:
        return None

    original_sleep = asyncio.sleep
    asyncio.sleep = _no_sleep  # type: ignore[assignment]
    try:
        async with LetterboxdClient(settings, min_interval_seconds=0) as client:
            response = await client.get("/flaky/")
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]
    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_get_respects_rate_limit() -> None:
    settings = _make_settings()
    respx.get("https://letterboxd.com/a/").mock(return_value=httpx.Response(200, text="a"))
    respx.get("https://letterboxd.com/b/").mock(return_value=httpx.Response(200, text="b"))
    async with LetterboxdClient(settings, min_interval_seconds=0.05) as client:
        start = time.monotonic()
        await client.get("/a/")
        await client.get("/b/")
        elapsed = time.monotonic() - start
    assert elapsed >= 0.05
