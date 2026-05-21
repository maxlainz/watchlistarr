from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import fixture_text
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.discovery import discover_lists


@respx.mock
async def test_discovery_creates_new_lists_disabled(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.commit()

    respx.get("https://letterboxd.com/alice/lists/").mock(
        return_value=httpx.Response(200, text=fixture_text("lists_index.html"))
    )

    discovered = await discover_lists(factory, letterboxd_client, user)
    assert len(discovered) == 3
    assert all(row.enabled is False for row in discovered)
    slugs = sorted(row.slug for row in discovered)
    assert slugs == ["2010s-must-watch", "empty-list", "favs"]


@respx.mock
async def test_discovery_disables_missing_lists(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    old = ListModel(
        user_id=user.id,
        source_type=SourceType.LIST,
        letterboxd_list_id="99999999",
        slug="gone",
        name="Gone",
        enabled=True,
    )
    session.add(old)
    await session.commit()

    respx.get("https://letterboxd.com/alice/lists/").mock(
        return_value=httpx.Response(200, text=fixture_text("lists_index.html"))
    )

    await discover_lists(factory, letterboxd_client, user)

    async with factory() as verify:
        refreshed = (
            await verify.execute(
                select(ListModel).where(ListModel.letterboxd_list_id == "99999999")
            )
        ).scalar_one()
        assert refreshed.enabled is False
