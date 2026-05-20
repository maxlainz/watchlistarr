from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.film_page import parse_film_page

logger = structlog.get_logger(__name__)


async def resolve_film(session: AsyncSession, client: LetterboxdClient, slug: str) -> Film | None:
    existing = (
        await session.execute(select(Film).where(Film.letterboxd_slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    response = await client.get(f"/film/{slug}/")
    data = parse_film_page(response.text, slug=slug)
    if data.tmdb_type != "movie" or data.tmdb_id is None:
        logger.info(
            "film.skipped",
            slug=slug,
            tmdb_type=data.tmdb_type,
            tmdb_id=data.tmdb_id,
        )
        return None

    by_tmdb = await session.get(Film, data.tmdb_id)
    if by_tmdb is not None:
        by_tmdb.letterboxd_slug = slug
        if data.title:
            by_tmdb.title = data.title
        if data.year:
            by_tmdb.year = data.year
        await session.flush()
        return by_tmdb

    film = Film(
        tmdb_id=data.tmdb_id,
        letterboxd_slug=slug,
        title=data.title or slug,
        year=data.year,
        tmdb_type=data.tmdb_type,
    )
    session.add(film)
    await session.flush()
    return film
