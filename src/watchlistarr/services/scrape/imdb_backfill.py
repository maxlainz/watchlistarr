from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.films import Film
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.film_resolver import resolve_film

logger = structlog.get_logger(__name__)


async def backfill_missing_imdb_ids(
    session: AsyncSession,
    client: LetterboxdClient,
    *,
    limit: int | None = None,
) -> int:
    """Re-resuelve films con ``imdb_id IS NULL`` para enriquecerlos.

    Recorre slugs sin imdb_id en orden estable y los pasa por ``resolve_film``,
    que internamente re-fetcha la ficha de Letterboxd cuando detecta el campo
    vacío. Commit por film para liberar el write-lock entre fetches HTTP.

    Devuelve el número de films que terminaron con ``imdb_id`` populado.
    """
    query = select(Film.letterboxd_slug).where(Film.imdb_id.is_(None))
    if limit is not None:
        query = query.limit(limit)
    slugs = list((await session.execute(query)).scalars().all())

    enriched = 0
    for slug in slugs:
        film = await resolve_film(session, client, slug)
        if film is not None and film.imdb_id is not None:
            enriched += 1
        await session.commit()

    logger.info("imdb_backfill.done", attempted=len(slugs), enriched=enriched)
    return enriched
