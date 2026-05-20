from __future__ import annotations

import asyncio
import time
from types import TracebackType

import httpx
import structlog

from watchlistarr.config import Settings

logger = structlog.get_logger(__name__)

BASE_URL = "https://letterboxd.com"
MIN_INTERVAL_SECONDS = 2.0
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3


class LetterboxdOfflineError(RuntimeError):
    """Lanzado cuando LETTERBOXD_OFFLINE=true bloquea una request."""


class LetterboxdClient:
    """Wrapper async sobre httpx con UA, rate-limit por host y retries 5xx."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = BASE_URL,
        min_interval_seconds: float = MIN_INTERVAL_SECONDS,
    ) -> None:
        self._settings = settings
        self._base_url = base_url
        self._min_interval = min_interval_seconds
        kwargs: dict[str, object] = {
            "timeout": TIMEOUT_SECONDS,
            "headers": {"User-Agent": settings.user_agent},
            "follow_redirects": True,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]
        self._lock = asyncio.Lock()
        self._last_request_monotonic: float | None = None

    async def __aenter__(self) -> LetterboxdClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str) -> httpx.Response:
        if self._settings.letterboxd_offline:
            raise LetterboxdOfflineError(f"LETTERBOXD_OFFLINE=true: GET {path} bloqueado")
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        async with self._lock:
            await self._respect_rate_limit()
            response = await self._request_with_retries(url)
            self._last_request_monotonic = time.monotonic()
        return response

    async def text(self, path: str) -> str:
        response = await self.get(path)
        return response.text

    async def _respect_rate_limit(self) -> None:
        if self._last_request_monotonic is None:
            return
        elapsed = time.monotonic() - self._last_request_monotonic
        wait = self._min_interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)

    async def _request_with_retries(self, url: str) -> httpx.Response:
        backoff = 1.0
        response: httpx.Response | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = await self._client.get(url)
            status = response.status_code
            if status == 403:
                logger.warning("letterboxd.forbidden", url=url, status=403)
                response.raise_for_status()
            if status >= 500 and attempt < MAX_ATTEMPTS:
                logger.warning("letterboxd.retry_5xx", url=url, status=status, attempt=attempt)
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            response.raise_for_status()
            return response
        assert response is not None
        return response
