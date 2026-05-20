from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import fixture_text
from watchlistarr.models.enums import SourceType
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.initial_run import (
    UserValidationError,
    run_initial_for_user,
    validate_username,
)


def _stub_film_page(slug: str, tmdb_id: int) -> None:
    html = f"""
    <html>
      <head><meta property="og:title" content="{slug} (2020)"></head>
      <body data-tmdb-type="movie" data-tmdb-id="{tmdb_id}"></body>
    </html>
    """
    respx.get(f"https://letterboxd.com/film/{slug}/").mock(
        return_value=httpx.Response(200, text=html)
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


@respx.mock
async def test_run_initial_for_user_populates_db(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()

    # Discovery vacío (sin listas custom).
    respx.get("https://letterboxd.com/alice/lists/").mock(
        return_value=httpx.Response(200, text="<html><body></body></html>")
    )
    # Watchlist
    respx.get("https://letterboxd.com/alice/watchlist/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210)
    _stub_film_page("parasite-2019", 496243)
    _stub_film_page("anatomy-of-a-fall", 915935)
    # Films backstop
    respx.get("https://letterboxd.com/alice/films/").mock(
        return_value=httpx.Response(200, text=fixture_text("films_p1.html"))
    )
    _stub_film_page("one-battle-after-another", 951277)
    _stub_film_page("mondays-in-the-sun", 54580)
    _stub_film_page("flow-2024", 823219)

    await run_initial_for_user(session, letterboxd_client, user)

    watchlists = list(
        (await session.execute(select(ListModel).where(ListModel.user_id == user.id)))
        .scalars()
        .all()
    )
    assert any(row.source_type is SourceType.WATCHLIST for row in watchlists)

    items = (await session.execute(select(ListItem))).scalars().all()
    assert {it.tmdb_id for it in items} == {447210, 496243, 915935}

    watched = list((await session.execute(select(WatchedFilm))).scalars().all())
    assert {w.tmdb_id for w in watched} == {951277, 54580, 823219}
