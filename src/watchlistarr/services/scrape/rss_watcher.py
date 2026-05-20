from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.base import utcnow
from watchlistarr.models.enums import WatchedSource
from watchlistarr.models.users import User
from watchlistarr.models.viewing_logs import ViewingLog
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.rss import parse_rss_feed

logger = structlog.get_logger(__name__)


async def poll_rss_for_user(session: AsyncSession, client: LetterboxdClient, user: User) -> int:
    response = await client.get(f"/{user.letterboxd_username}/rss/")
    events = parse_rss_feed(response.text)
    new_events = 0
    for event in events:
        existing_log = await session.get(ViewingLog, event.guid)
        if existing_log is not None:
            continue
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

        watched = await session.get(WatchedFilm, (user.id, event.tmdb_id))
        if watched is None:
            session.add(
                WatchedFilm(
                    user_id=user.id,
                    tmdb_id=event.tmdb_id,
                    first_seen_watched_at=utcnow(),
                    last_seen_watched_at=utcnow(),
                    source=WatchedSource.RSS,
                )
            )
        else:
            watched.last_seen_watched_at = utcnow()
        new_events += 1
    await session.flush()
    logger.info("rss.poll", user_id=user.id, total=len(events), new=new_events)
    return new_events
