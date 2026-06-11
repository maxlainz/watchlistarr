from __future__ import annotations

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.film_resolver import resolve_films


def _stub_film_page(
    slug: str, tmdb_id: int, *, year: int = 2020, imdb_id: str | None = None
) -> None:
    imdb_link = (
        f'<a href="http://www.imdb.com/title/{imdb_id}/maindetails">IMDb</a>' if imdb_id else ""
    )
    html = f"""
    <html>
      <head><meta property="og:title" content="{slug.title()} ({year})"></head>
      <body data-tmdb-type="movie" data-tmdb-id="{tmdb_id}">{imdb_link}</body>
    </html>
    """
    respx.get(f"https://letterboxd.com/film/{slug}/").mock(
        return_value=httpx.Response(200, text=html)
    )


@respx.mock
async def test_resolve_films_slug_remap_supersedes_old_row(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    """Regresión: la página de un slug cacheado pasa a mapear a otro tmdb_id.
    El insert del film nuevo chocaba con UNIQUE(letterboxd_slug) de la fila vieja."""
    session.add(Film(tmdb_id=100, letterboxd_slug="the-movie", title="The Movie", year=2020))
    await session.commit()

    _stub_film_page("the-movie", 999, imdb_id="tt0000999")

    resolved = await resolve_films(factory, letterboxd_client, ["the-movie"])

    assert resolved["the-movie"].tmdb_id == 999
    async with factory() as verify:
        films = {f.tmdb_id: f for f in (await verify.execute(select(Film))).scalars().all()}
        assert films[999].letterboxd_slug == "the-movie"
        assert films[100].letterboxd_slug == "the-movie--superseded-100"


@respx.mock
async def test_resolve_films_imdb_remap_clears_old_row(
    session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    letterboxd_client: LetterboxdClient,
) -> None:
    """Regresión: el imdb_id de la ficha nueva ya pertenecía a otra fila —
    chocaba con UNIQUE(imdb_id)."""
    session.add(
        Film(
            tmdb_id=100,
            letterboxd_slug="old-entry",
            title="Old Entry",
            year=2020,
            imdb_id="tt0000123",
        )
    )
    await session.commit()

    _stub_film_page("new-entry", 999, imdb_id="tt0000123")

    resolved = await resolve_films(factory, letterboxd_client, ["new-entry"])

    assert resolved["new-entry"].tmdb_id == 999
    async with factory() as verify:
        films = {f.tmdb_id: f for f in (await verify.execute(select(Film))).scalars().all()}
        assert films[999].imdb_id == "tt0000123"
        assert films[100].imdb_id is None
