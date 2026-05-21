"""Regresión del bug `database is locked`: dos scrapers que escriben tienen que
poder convivir en paralelo sin tirar `OperationalError`.

Antes del refactor a fetch-first / write-last, `_with_user` mantenía abierta una
transacción de escritura durante todos los fetches HTTP, y otra corrutina
ejecutándose en paralelo se topaba con el write-lock de SQLite. Tras el refactor,
cada scraper hace HTTP fuera de toda transacción y solo abre sesiones cortas
para escribir.
"""

from __future__ import annotations

import asyncio

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import fixture_text
from watchlistarr.models.users import User
from watchlistarr.models.viewing_logs import ViewingLog
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.films_backstop import backstop_films_for_user
from watchlistarr.services.scrape.rss_watcher import poll_rss_for_user


@respx.mock
async def test_concurrent_rss_and_backstop_no_lock(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    user = User(letterboxd_username="maxlainz")
    session.add(user)
    await session.commit()

    respx.get("https://letterboxd.com/maxlainz/rss/").mock(
        return_value=httpx.Response(200, text=fixture_text("rss_feed.xml"))
    )
    respx.get("https://letterboxd.com/maxlainz/films/").mock(
        return_value=httpx.Response(200, text=fixture_text("films_p1.html"))
    )
    # Cualquier ficha de film mockeable como movie con tmdb_id arbitrario.
    respx.get(httpx.URL("https://letterboxd.com").join("")).pass_through()
    respx.route(url__regex=r"https://letterboxd\.com/film/[^/]+/$").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><head>"
                '<meta property="og:title" content="Mock (2020)">'
                "</head>"
                '<body data-tmdb-type="movie" data-tmdb-id="424242"></body>'
                "</html>"
            ),
        )
    )

    rss_task = poll_rss_for_user(factory, letterboxd_client, user)
    backstop_task = backstop_films_for_user(factory, letterboxd_client, user)
    await asyncio.gather(rss_task, backstop_task)

    logs = list((await session.execute(select(ViewingLog))).scalars().all())
    assert len(logs) >= 1
