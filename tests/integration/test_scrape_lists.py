from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import fixture_text
from watchlistarr.models.enums import SourceType, SyncStatus
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.lists import sync_list_full, sync_list_incremental


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


async def _make_user_list(session: AsyncSession) -> ListModel:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    lst = ListModel(
        user_id=user.id,
        source_type=SourceType.LIST,
        letterboxd_list_id="42",
        slug="favs",
        name="Favs",
        enabled=True,
    )
    session.add(lst)
    await session.flush()
    return lst


@respx.mock
async def test_sync_list_full_populates_items(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    lst = await _make_user_list(session)
    respx.get("https://letterboxd.com/alice/list/favs/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210)
    _stub_film_page("parasite-2019", 496243)
    _stub_film_page("anatomy-of-a-fall", 915935)

    await sync_list_full(session, letterboxd_client, lst)
    items = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    assert {it.tmdb_id for it in items} == {447210, 496243, 915935}
    assert lst.last_sync_status is SyncStatus.SUCCESS
    assert lst.film_count == 3


@respx.mock
async def test_sync_list_incremental_uses_added_earliest_when_paginated(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    lst = await _make_user_list(session)
    # Página 1 con paginación a 23.
    respx.get("https://letterboxd.com/alice/list/favs/").mock(
        return_value=httpx.Response(200, text=fixture_text("pagination_block.html"))
    )
    # Última página de added-earliest.
    respx.get("https://letterboxd.com/alice/list/favs/by/added-earliest/page/23/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("film-a", 1)
    _stub_film_page("3-faces", 447210)
    _stub_film_page("parasite-2019", 496243)
    _stub_film_page("anatomy-of-a-fall", 915935)

    await sync_list_incremental(session, letterboxd_client, lst)
    items = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    # Combina ambos sets.
    assert {it.tmdb_id for it in items} == {1, 447210, 496243, 915935}
