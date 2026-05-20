from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import get_settings
from watchlistarr.models.settings import Setting
from watchlistarr.services.settings import (
    ALL_KEYS,
    get_duration,
    get_int,
    seed_defaults,
    set_value,
)


async def test_seed_defaults_inserts_all_keys(session: AsyncSession) -> None:
    await seed_defaults(session)
    await session.commit()
    rows = (await session.execute(select(Setting.key))).scalars().all()
    assert set(rows) == set(ALL_KEYS)


async def test_seed_defaults_is_idempotent(session: AsyncSession) -> None:
    await seed_defaults(session)
    await seed_defaults(session)
    await session.commit()
    rows = (await session.execute(select(Setting.key))).scalars().all()
    assert len(rows) == len(ALL_KEYS)


async def test_get_duration_reads_default_then_override(session: AsyncSession) -> None:
    await seed_defaults(session)
    await session.commit()
    rss = await get_duration(session, "rss_interval")
    assert rss == get_settings().rss_interval

    await set_value(session, "rss_interval", timedelta(minutes=5))
    await session.commit()
    updated = await get_duration(session, "rss_interval")
    assert updated == timedelta(minutes=5)


async def test_get_int_reads_flap_threshold(session: AsyncSession) -> None:
    await seed_defaults(session)
    await session.commit()
    assert await get_int(session, "flap_confirm_scrapes") == get_settings().flap_confirm_scrapes
    await set_value(session, "flap_confirm_scrapes", 7)
    await session.commit()
    assert await get_int(session, "flap_confirm_scrapes") == 7
