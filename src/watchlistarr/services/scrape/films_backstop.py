from __future__ import annotations

import structlog
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import WatchedSource
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.films import parse_films_page
from watchlistarr.services.scrape.film_resolver import resolve_films

logger = structlog.get_logger(__name__)


async def backstop_films_for_user(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    user: User,
) -> None:
    """Pobla ``watched_films`` con lo que aparece en ``/{user}/films/`` página 1.

    HTTP fuera de toda transacción + escritura final en sesión corta.
    """
    response = await client.get(f"/{user.letterboxd_username}/films/")
    refs = parse_films_page(response.text)
    slugs = [ref.slug for ref in refs]

    resolved = await resolve_films(factory, client, slugs)
    if not resolved:
        logger.info(
            "films_backstop.done",
            user_id=user.id,
            username=user.letterboxd_username,
            items=len(refs),
            inserted=0,
        )
        return

    tmdb_ids = [film.tmdb_id for film in resolved.values()]

    async with factory() as session:
        watched_rows = (
            await session.execute(
                select(WatchedFilm.user_id, WatchedFilm.tmdb_id).where(
                    tuple_(WatchedFilm.user_id, WatchedFilm.tmdb_id).in_(
                        [(user.id, tid) for tid in tmdb_ids]
                    )
                )
            )
        ).all()
        existing_keys: set[tuple[int, int]] = {(row[0], row[1]) for row in watched_rows}

        inserted = 0
        for film in resolved.values():
            key = (user.id, film.tmdb_id)
            now = utcnow()
            if key in existing_keys:
                row = await session.get(WatchedFilm, key)
                if row is not None:
                    row.last_seen_watched_at = now
            else:
                session.add(
                    WatchedFilm(
                        user_id=user.id,
                        tmdb_id=film.tmdb_id,
                        first_seen_watched_at=now,
                        last_seen_watched_at=now,
                        source=WatchedSource.FILMS_PAGE,
                    )
                )
                inserted += 1
                existing_keys.add(key)

        await session.commit()

    logger.info(
        "films_backstop.done",
        user_id=user.id,
        username=user.letterboxd_username,
        items=len(refs),
        inserted=inserted,
    )
