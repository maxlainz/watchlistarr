from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.film_resolver import resolve_films

logger = structlog.get_logger(__name__)


async def backfill_missing_ratings(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    *,
    limit: int | None = None,
) -> int:
    """Re-resuelve films con ``letterboxd_avg_rating IS NULL`` para poblarlos.

    Delega en ``resolve_films`` (que ya considera el rating como parte de la
    condición de cache) y devuelve cuántos terminaron con rating no nulo.
    """
    async with factory() as session:
        query = select(Film.letterboxd_slug).where(Film.letterboxd_avg_rating.is_(None))
        if limit is not None:
            query = query.limit(limit)
        slugs = list((await session.execute(query)).scalars().all())

    if not slugs:
        logger.info("rating_backfill.done", attempted=0, enriched=0)
        return 0

    await resolve_films(factory, client, slugs)

    async with factory() as session:
        enriched = (
            await session.execute(
                select(func.count())
                .select_from(Film)
                .where(
                    Film.letterboxd_slug.in_(slugs),
                    Film.letterboxd_avg_rating.is_not(None),
                )
            )
        ).scalar_one()

    logger.info("rating_backfill.done", attempted=len(slugs), enriched=enriched)
    return int(enriched)
