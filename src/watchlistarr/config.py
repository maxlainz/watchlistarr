from __future__ import annotations

import re
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_DURATION_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(value: object) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, int):
        return timedelta(seconds=value)
    if isinstance(value, str):
        match = _DURATION_RE.match(value)
        if not match:
            raise ValueError(f"duración inválida: {value!r} (formato esperado: '15m', '1h', '7d')")
        n, unit = int(match.group(1)), match.group(2).lower()
        return timedelta(seconds=n * _DURATION_UNITS[unit])
    raise TypeError(f"tipo no soportado para duración: {type(value).__name__}")


Duration = Annotated[timedelta, BeforeValidator(_parse_duration)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    http_port: int = 8080
    log_level: str = "info"
    log_format: str = "plain"
    database_url: str = "sqlite+aiosqlite:///data/watchlistarr.db"
    user_agent: str = "watchlistarr/0.1.0 (+https://github.com/maxlainz/watchlistarr)"
    letterboxd_offline: bool = False

    rss_interval: Duration = Field(default=timedelta(minutes=15))
    watchlist_incremental_interval: Duration = Field(default=timedelta(hours=1))
    watchlist_full_interval: Duration = Field(default=timedelta(hours=24))
    lists_incremental_interval: Duration = Field(default=timedelta(hours=6))
    lists_full_interval: Duration = Field(default=timedelta(days=7))
    films_backstop_interval: Duration = Field(default=timedelta(hours=24))
    discovery_interval: Duration = Field(default=timedelta(days=7))
    rotation_tick_interval: Duration = Field(default=timedelta(hours=1))

    flap_confirm_scrapes: int = 3


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
