from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    await session.commit()
    return lst


@respx.mock
async def test_sync_list_full_populates_items(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    lst = await _make_user_list(session)
    respx.get("https://letterboxd.com/alice/list/favs/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210)
    _stub_film_page("parasite-2019", 496243)
    _stub_film_page("anatomy-of-a-fall", 915935)

    await sync_list_full(factory, letterboxd_client, lst.id)
    async with factory() as verify:
        items = (
            (await verify.execute(select(ListItem).where(ListItem.list_id == lst.id)))
            .scalars()
            .all()
        )
        assert {it.tmdb_id for it in items} == {447210, 496243, 915935}
        refreshed = (
            await verify.execute(select(ListModel).where(ListModel.id == lst.id))
        ).scalar_one()
        assert refreshed.last_sync_status is SyncStatus.SUCCESS
        assert refreshed.film_count == 3


@respx.mock
async def test_sync_list_incremental_uses_added_earliest_when_paginated(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
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

    await sync_list_incremental(factory, letterboxd_client, lst.id)
    items = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    # Combina ambos sets.
    assert {it.tmdb_id for it in items} == {1, 447210, 496243, 915935}


@respx.mock
async def test_sync_list_incremental_preserves_existing_positions(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    """Regresión: incremental no debe pisar la position de items ya existentes.
    El slice escrapeado (página 1 + última) no refleja la position real."""
    from watchlistarr.models.films import Film

    lst = await _make_user_list(session)
    # Simular un full sync previo: 3 items con positions reales [50, 51, 52].
    for tmdb_id, slug, pos in [
        (447210, "3-faces", 50),
        (496243, "parasite-2019", 51),
        (915935, "anatomy-of-a-fall", 52),
    ]:
        session.add(Film(tmdb_id=tmdb_id, letterboxd_slug=slug, title=slug, year=2020))
        session.add(ListItem(list_id=lst.id, tmdb_id=tmdb_id, position=pos))
    await session.commit()

    # Incremental que vuelve a ver los mismos slugs en página 1 (sin paginación).
    respx.get("https://letterboxd.com/alice/list/favs/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210)
    _stub_film_page("parasite-2019", 496243)
    _stub_film_page("anatomy-of-a-fall", 915935)

    await sync_list_incremental(factory, letterboxd_client, lst.id)

    async with factory() as verify:
        items = (
            (await verify.execute(select(ListItem).where(ListItem.list_id == lst.id)))
            .scalars()
            .all()
        )
    positions_by_tmdb = {it.tmdb_id: it.position for it in items}
    assert positions_by_tmdb == {447210: 50, 496243: 51, 915935: 52}
