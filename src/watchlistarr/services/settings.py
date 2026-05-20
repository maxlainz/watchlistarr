from __future__ import annotations

from datetime import timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import Settings, get_settings
from watchlistarr.models.settings import Setting

logger = structlog.get_logger(__name__)

DURATION_KEYS: tuple[str, ...] = (
    "rss_interval",
    "watchlist_incremental_interval",
    "watchlist_full_interval",
    "lists_incremental_interval",
    "lists_full_interval",
    "films_backstop_interval",
    "discovery_interval",
    "rotation_tick_interval",
)
INT_KEYS: tuple[str, ...] = ("flap_confirm_scrapes",)
ALL_KEYS: tuple[str, ...] = (*DURATION_KEYS, *INT_KEYS)


def _serialize(value: object) -> str:
    if isinstance(value, timedelta):
        return str(int(value.total_seconds()))
    return str(value)


def _to_int(value: str) -> int:
    return int(value)


def _to_timedelta(value: str) -> timedelta:
    return timedelta(seconds=int(value))


async def seed_defaults(session: AsyncSession, env_settings: Settings | None = None) -> None:
    env_settings = env_settings or get_settings()
    existing = {
        row[0]
        for row in (
            await session.execute(select(Setting.key).where(Setting.key.in_(ALL_KEYS)))
        ).all()
    }
    inserted: list[str] = []
    for key in ALL_KEYS:
        if key in existing:
            continue
        value = getattr(env_settings, key)
        session.add(Setting(key=key, value=_serialize(value)))
        inserted.append(key)
    if inserted:
        await session.flush()
        logger.info("settings.seeded", keys=inserted)


async def get_duration(session: AsyncSession, key: str) -> timedelta:
    if key not in DURATION_KEYS:
        raise KeyError(f"setting {key!r} no es de tipo duración")
    row: str | None = (
        await session.execute(select(Setting.value).where(Setting.key == key))
    ).scalar_one_or_none()
    if row is None:
        fallback: timedelta = getattr(get_settings(), key)
        return fallback
    return _to_timedelta(row)


async def get_int(session: AsyncSession, key: str) -> int:
    if key not in INT_KEYS:
        raise KeyError(f"setting {key!r} no es de tipo entero")
    row: str | None = (
        await session.execute(select(Setting.value).where(Setting.key == key))
    ).scalar_one_or_none()
    if row is None:
        return int(getattr(get_settings(), key))
    return _to_int(row)


async def set_value(session: AsyncSession, key: str, value: object) -> None:
    if key not in ALL_KEYS:
        raise KeyError(f"setting {key!r} no es reconocido")
    serialized = _serialize(value)
    existing = (
        await session.execute(select(Setting).where(Setting.key == key))
    ).scalar_one_or_none()
    if existing is None:
        session.add(Setting(key=key, value=serialized))
    else:
        existing.value = serialized
    await session.flush()
