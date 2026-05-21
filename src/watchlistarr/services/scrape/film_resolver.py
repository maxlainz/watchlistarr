from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.film_page import parse_film_page

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedFilm:
    """Snapshot plano de un film. Seguro de cruzar boundaries de sesión."""

    tmdb_id: int
    letterboxd_slug: str
    title: str
    year: int | None
    imdb_id: str | None


def _to_resolved(film: Film) -> ResolvedFilm:
    return ResolvedFilm(
        tmdb_id=film.tmdb_id,
        letterboxd_slug=film.letterboxd_slug,
        title=film.title,
        year=film.year,
        imdb_id=film.imdb_id,
    )


async def resolve_films(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    slugs: list[str],
) -> dict[str, ResolvedFilm]:
    """Resuelve un batch de slugs a ``ResolvedFilm`` evitando mantener una
    transacción abierta durante los fetches HTTP.

    Pipeline:
        A. Sesión corta de lectura: cache de films con imdb_id ya populado.
        B. HTTP puro: fetch de las fichas de los slugs no cacheados (o sin imdb).
        C. Sesión corta de escritura: upsert de films nuevos/enriquecidos.

    Devuelve un dict ``slug -> ResolvedFilm`` solo con films válidos
    (``tmdb_type='movie'`` y ``tmdb_id`` no nulo).
    """
    if not slugs:
        return {}

    unique_slugs = list(dict.fromkeys(slugs))

    async with factory() as session:
        cached_rows = list(
            (await session.execute(select(Film).where(Film.letterboxd_slug.in_(unique_slugs))))
            .scalars()
            .all()
        )

    cached_by_slug = {f.letterboxd_slug: f for f in cached_rows}
    resolved: dict[str, ResolvedFilm] = {}
    needs_fetch: list[str] = []
    for slug in unique_slugs:
        film = cached_by_slug.get(slug)
        if film is not None and film.imdb_id is not None:
            resolved[slug] = _to_resolved(film)
        else:
            needs_fetch.append(slug)

    fetched: dict[str, object] = {}
    for slug in needs_fetch:
        logger.info("film.resolve", slug=slug)
        response = await client.get(f"/film/{slug}/")
        fetched[slug] = parse_film_page(response.text, slug=slug)

    if not fetched:
        return resolved

    async with factory() as session:
        for slug, data in fetched.items():
            tmdb_type = getattr(data, "tmdb_type", "")
            tmdb_id = getattr(data, "tmdb_id", None)
            if tmdb_type != "movie" or tmdb_id is None:
                logger.info("film.skipped", slug=slug, tmdb_type=tmdb_type, tmdb_id=tmdb_id)
                continue

            title = getattr(data, "title", None)
            year = getattr(data, "year", None)
            imdb_id = getattr(data, "imdb_id", None)

            existing_by_tmdb = await session.get(Film, tmdb_id)
            if existing_by_tmdb is not None:
                existing_by_tmdb.letterboxd_slug = slug
                if title:
                    existing_by_tmdb.title = title
                if year:
                    existing_by_tmdb.year = year
                if imdb_id and not existing_by_tmdb.imdb_id:
                    existing_by_tmdb.imdb_id = imdb_id
                row = existing_by_tmdb
            else:
                row = Film(
                    tmdb_id=tmdb_id,
                    letterboxd_slug=slug,
                    title=title or slug,
                    year=year,
                    tmdb_type=tmdb_type,
                    imdb_id=imdb_id,
                )
                session.add(row)
            await session.flush()
            resolved[slug] = _to_resolved(row)
        await session.commit()

    return resolved
