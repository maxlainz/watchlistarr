from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import fixture_text
from watchlistarr.models.users import User
from watchlistarr.models.viewing_logs import ViewingLog
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.rss_watcher import poll_rss_for_user


@respx.mock
async def test_poll_rss_creates_viewing_logs_and_watched_films(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    user = User(letterboxd_username="maxlainz")
    session.add(user)
    await session.flush()

    respx.get("https://letterboxd.com/maxlainz/rss/").mock(
        return_value=httpx.Response(200, text=fixture_text("rss_feed.xml"))
    )
    new = await poll_rss_for_user(session, letterboxd_client, user)
    assert new == 2

    logs = list((await session.execute(select(ViewingLog))).scalars().all())
    assert {row.letterboxd_guid for row in logs} == {
        "letterboxd-watch-1310048973",
        "letterboxd-review-1153149850",
    }

    watched = list((await session.execute(select(WatchedFilm))).scalars().all())
    assert {w.tmdb_id for w in watched} == {54580, 823219}


@respx.mock
async def test_poll_rss_dedup_by_guid(
    session: AsyncSession, letterboxd_client: LetterboxdClient
) -> None:
    user = User(letterboxd_username="maxlainz")
    session.add(user)
    await session.flush()

    respx.get("https://letterboxd.com/maxlainz/rss/").mock(
        return_value=httpx.Response(200, text=fixture_text("rss_feed.xml"))
    )
    await poll_rss_for_user(session, letterboxd_client, user)
    second = await poll_rss_for_user(session, letterboxd_client, user)
    assert second == 0
