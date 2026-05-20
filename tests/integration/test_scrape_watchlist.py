from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import fixture_text
from watchlistarr.models.enums import SourceType, SyncStatus
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.watchlist import (
    sync_watchlist_full,
    sync_watchlist_incremental,
)


def _stub_film_page(slug: str, tmdb_id: int, *, year: int = 2020) -> None:
    html = f"""
    <html>
      <head><meta property="og:title" content="{slug.title()} ({year})"></head>
      <body data-tmdb-type="movie" data-tmdb-id="{tmdb_id}"></body>
    </html>
    """
    respx.get(f"https://letterboxd.com/film/{slug}/").mock(
        return_value=httpx.Response(200, text=html)
    )


async def _seed_user_with_watchlist(session: AsyncSession, username: str) -> ListModel:
    user = User(letterboxd_username=username)
    session.add(user)
    await session.flush()
    watchlist = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="Watchlist",
        enabled=True,
    )
    session.add(watchlist)
    await session.flush()
    return watchlist


@respx.mock
async def test_sync_watchlist_full_creates_list_items(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    watchlist = await _seed_user_with_watchlist(session, "alice")
    respx.get("https://letterboxd.com/alice/watchlist/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210, year=2018)
    _stub_film_page("parasite-2019", 496243, year=2019)
    _stub_film_page("anatomy-of-a-fall", 915935, year=2023)

    await sync_watchlist_full(session, letterboxd_client, watchlist)

    items = (
        (await session.execute(select(ListItem).where(ListItem.list_id == watchlist.id)))
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    assert tmdb_ids == [447210, 496243, 915935]
    assert watchlist.last_sync_status is SyncStatus.SUCCESS

    films = list((await session.execute(select(Film))).scalars().all())
    assert {f.tmdb_id for f in films} == {447210, 496243, 915935}


@respx.mock
async def test_sync_watchlist_incremental_only_adds(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    watchlist = await _seed_user_with_watchlist(session, "alice")
    # Estado previo: 1 item.
    session.add(Film(tmdb_id=1, letterboxd_slug="old", title="Old", year=2010))
    session.add(ListItem(list_id=watchlist.id, tmdb_id=1, position=99))
    await session.flush()

    respx.get("https://letterboxd.com/alice/watchlist/").mock(
        return_value=httpx.Response(200, text=fixture_text("watchlist_p1.html"))
    )
    _stub_film_page("3-faces", 447210, year=2018)
    _stub_film_page("parasite-2019", 496243, year=2019)
    _stub_film_page("anatomy-of-a-fall", 915935, year=2023)

    await sync_watchlist_incremental(session, letterboxd_client, watchlist)

    items = (
        (await session.execute(select(ListItem).where(ListItem.list_id == watchlist.id)))
        .scalars()
        .all()
    )
    tmdb_ids = sorted(it.tmdb_id for it in items)
    # Item antiguo NO se elimina porque es incremental.
    assert tmdb_ids == [1, 447210, 496243, 915935]
