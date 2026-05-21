from __future__ import annotations

import structlog
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import WatchedSource
from watchlistarr.models.users import User
from watchlistarr.models.viewing_logs import ViewingLog
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.rss import parse_rss_feed

logger = structlog.get_logger(__name__)


async def poll_rss_for_user(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    user: User,
) -> int:
    """Fetch del RSS público y upsert de viewing_logs + watched_films.

    Fase HTTP fuera de toda transacción; una única sesión corta de escritura.
    """
    response = await client.get(f"/{user.letterboxd_username}/rss/")
    events = parse_rss_feed(response.text)
    if not events:
        logger.info("rss.poll", user_id=user.id, total=0, new=0)
        return 0

    guids = [event.guid for event in events]
    tmdb_ids = list({event.tmdb_id for event in events})

    async with factory() as session:
        existing_guids: set[str] = set(
            (
                await session.execute(
                    select(ViewingLog.letterboxd_guid).where(ViewingLog.letterboxd_guid.in_(guids))
                )
            )
            .scalars()
            .all()
        )
        watched_rows = (
            await session.execute(
                select(WatchedFilm.user_id, WatchedFilm.tmdb_id).where(
                    tuple_(WatchedFilm.user_id, WatchedFilm.tmdb_id).in_(
                        [(user.id, tid) for tid in tmdb_ids]
                    )
                )
            )
        ).all()
        existing_watched_keys: set[tuple[int, int]] = {(row[0], row[1]) for row in watched_rows}

        new_events = 0
        seen_new_watched: set[int] = set()
        for event in events:
            if event.guid in existing_guids:
                continue
            now = utcnow()
            session.add(
                ViewingLog(
                    letterboxd_guid=event.guid,
                    user_id=user.id,
                    tmdb_id=event.tmdb_id,
                    watched_date=event.watched_date,
                    rating=event.rating,
                    member_like=event.member_like,
                )
            )

            key = (user.id, event.tmdb_id)
            if key in existing_watched_keys:
                watched = await session.get(WatchedFilm, key)
                if watched is not None:
                    watched.last_seen_watched_at = now
            elif event.tmdb_id not in seen_new_watched:
                session.add(
                    WatchedFilm(
                        user_id=user.id,
                        tmdb_id=event.tmdb_id,
                        first_seen_watched_at=now,
                        last_seen_watched_at=now,
                        source=WatchedSource.RSS,
                    )
                )
                seen_new_watched.add(event.tmdb_id)
            new_events += 1

        await session.commit()

    logger.info("rss.poll", user_id=user.id, total=len(events), new=new_events)
    return new_events
