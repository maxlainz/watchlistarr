from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.film_resolver import resolve_films

logger = structlog.get_logger(__name__)


async def backfill_missing_imdb_ids(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    *,
    limit: int | None = None,
) -> int:
    """Re-resuelve films con ``imdb_id IS NULL`` para enriquecerlos.

    Delega en ``resolve_films`` que gestiona sus propias mini-sesiones y separa
    HTTP de escrituras para no bloquear el write-lock de SQLite.

    Devuelve el número de films que terminaron con ``imdb_id`` populado.
    """
    async with factory() as session:
        query = select(Film.letterboxd_slug).where(Film.imdb_id.is_(None))
        if limit is not None:
            query = query.limit(limit)
        slugs = list((await session.execute(query)).scalars().all())

    if not slugs:
        logger.info("imdb_backfill.done", attempted=0, enriched=0)
        return 0

    resolved = await resolve_films(factory, client, slugs)
    enriched = sum(1 for f in resolved.values() if f.imdb_id is not None)
    logger.info("imdb_backfill.done", attempted=len(slugs), enriched=enriched)
    return enriched
