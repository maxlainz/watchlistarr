from __future__ import annotations

from collections.abc import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.scrape.film_resolver import ResolvedFilm

logger = structlog.get_logger(__name__)


async def reconcile_full_scrape(
    session: AsyncSession,
    *,
    list_id: int,
    user_id: int,
    scraped_films: Iterable[ResolvedFilm],
    threshold: int,
) -> None:
    """Aplica anti-flap a las eliminaciones detectadas por un scrape completo.

    Para cada `list_items` que ya no aparece en `scraped_films`:
      1. Si la peli ya está en `watched_films` del owner → eliminar.
      2. Si hay un film scraped con mismo (title, year) → rename: actualizar slug y mantener.
      3. Si no, incrementar `pending_removal_count`; eliminar al llegar al umbral.
    Items que reaparecen tienen su contador reseteado por el orquestador.
    """
    scraped_films_list = list(scraped_films)
    scraped_tmdb_ids = {f.tmdb_id for f in scraped_films_list}
    scraped_by_title_year: dict[tuple[str, int | None], ResolvedFilm] = {
        (f.title, f.year): f for f in scraped_films_list
    }

    existing = (
        (await session.execute(select(ListItem).where(ListItem.list_id == list_id))).scalars().all()
    )

    for item in existing:
        if item.tmdb_id in scraped_tmdb_ids:
            continue
        film = await session.get(Film, item.tmdb_id)

        watched = await session.get(WatchedFilm, (user_id, item.tmdb_id))
        if watched is not None:
            logger.info(
                "anti_flap.removed_watched",
                list_id=list_id,
                tmdb_id=item.tmdb_id,
            )
            await session.delete(item)
            continue

        rename_target = (
            scraped_by_title_year.get((film.title, film.year)) if film is not None else None
        )
        if rename_target is not None and rename_target.tmdb_id != item.tmdb_id:
            logger.info(
                "anti_flap.rename_detected",
                list_id=list_id,
                old_tmdb_id=item.tmdb_id,
                new_tmdb_id=rename_target.tmdb_id,
            )
            if film is not None:
                film.letterboxd_slug = rename_target.letterboxd_slug
            continue

        item.pending_removal_count += 1
        if item.pending_removal_count >= threshold:
            logger.info(
                "anti_flap.removed_threshold",
                list_id=list_id,
                tmdb_id=item.tmdb_id,
                count=item.pending_removal_count,
            )
            await session.delete(item)
