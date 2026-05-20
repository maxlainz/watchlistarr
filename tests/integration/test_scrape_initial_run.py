from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.initial_run import (
    UserValidationError,
    ensure_watchlist_row,
    validate_username,
)


@respx.mock
async def test_validate_username_accepts_member(
    letterboxd_client: LetterboxdClient,
) -> None:
    respx.get("https://letterboxd.com/alice/").mock(
        return_value=httpx.Response(200, text="ok", headers={"x-letterboxd-type": "Member"})
    )
    assert await validate_username(letterboxd_client, "alice") == "alice"


@respx.mock
async def test_validate_username_rejects_non_member(
    letterboxd_client: LetterboxdClient,
) -> None:
    respx.get("https://letterboxd.com/notuser/").mock(
        return_value=httpx.Response(200, text="ok", headers={"x-letterboxd-type": "List"})
    )
    with pytest.raises(UserValidationError):
        await validate_username(letterboxd_client, "notuser")


async def test_validate_username_rejects_reserved(
    letterboxd_client: LetterboxdClient,
) -> None:
    with pytest.raises(UserValidationError):
        await validate_username(letterboxd_client, "admin")


async def test_ensure_watchlist_row_creates_disabled(session: AsyncSession) -> None:
    """Adding a user must create a watchlist row in DB but leave it disabled
    so the user opts in explicitly before any scrape."""
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()

    row = await ensure_watchlist_row(session, user)
    assert row.source_type is SourceType.WATCHLIST
    assert row.enabled is False
    assert row.slug == "watchlist"


async def test_ensure_watchlist_row_idempotent(session: AsyncSession) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()

    a = await ensure_watchlist_row(session, user)
    b = await ensure_watchlist_row(session, user)
    assert a.id == b.id

    rows = list(
        (
            await session.execute(
                select(ListModel).where(
                    ListModel.user_id == user.id,
                    ListModel.source_type == SourceType.WATCHLIST,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
