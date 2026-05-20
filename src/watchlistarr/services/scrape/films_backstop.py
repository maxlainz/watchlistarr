from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import WatchedSource
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.films import parse_films_page
from watchlistarr.services.scrape.film_resolver import resolve_film

logger = structlog.get_logger(__name__)


_COMMIT_EVERY = 10


async def backstop_films_for_user(
    session: AsyncSession, client: LetterboxdClient, user: User
) -> None:
    response = await client.get(f"/{user.letterboxd_username}/films/")
    items = parse_films_page(response.text)
    inserted = 0
    for i, ref in enumerate(items, 1):
        film = await resolve_film(session, client, ref.slug)
        if film is not None:
            existing = await session.get(WatchedFilm, (user.id, film.tmdb_id))
            if existing is not None:
                existing.last_seen_watched_at = utcnow()
            else:
                session.add(
                    WatchedFilm(
                        user_id=user.id,
                        tmdb_id=film.tmdb_id,
                        first_seen_watched_at=utcnow(),
                        last_seen_watched_at=utcnow(),
                        source=WatchedSource.FILMS_PAGE,
                    )
                )
                inserted += 1
        if i % _COMMIT_EVERY == 0:
            await session.commit()
    await session.commit()
    logger.info("films_backstop.done", user_id=user.id, items=len(items), inserted=inserted)
