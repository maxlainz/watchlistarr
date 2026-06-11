from __future__ import annotations

from collections.abc import Iterable

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.models.enums import WatchedSource
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.letterboxd.films import parse_films_page
from watchlistarr.services.scrape.film_resolver import ResolvedFilm

logger = structlog.get_logger(__name__)


async def _unexplained_disappearances(
    session: AsyncSession,
    *,
    list_id: int,
    user_id: int,
    scraped_tmdb_ids: set[int],
) -> list[int]:
    """Tmdb_ids de ``list_items`` que desaparecieron del scrape sin estar en
    ``watched_films`` del owner."""
    rows = (
        await session.execute(select(ListItem.tmdb_id).where(ListItem.list_id == list_id))
    ).all()
    missing = [tmdb_id for (tmdb_id,) in rows if tmdb_id not in scraped_tmdb_ids]
    if not missing:
        return []
    watched = {
        row[0]
        for row in (
            await session.execute(
                select(WatchedFilm.tmdb_id).where(
                    WatchedFilm.user_id == user_id,
                    WatchedFilm.tmdb_id.in_(missing),
                )
            )
        ).all()
    }
    return [tmdb_id for tmdb_id in missing if tmdb_id not in watched]


async def adhoc_films_backstop(
    factory: async_sessionmaker[AsyncSession],
    client: LetterboxdClient,
    *,
    username: str,
    list_id: int,
    user_id: int,
    scraped_tmdb_ids: set[int],
) -> set[int]:
    """Paso 3 del anti-flap: si hay desapariciones sin explicar, fetch a la
    página 1 de ``/{user}/films/`` para confirmar visionados que el RSS perdió.

    Se llama ANTES de abrir la sesión de escritura del full sync para no
    mantener el write-lock de SQLite durante HTTP. Los slugs se resuelven solo
    contra la DB (los candidatos ya existen en ``films``). Un fallo del fetch
    degrada al contador normal en vez de abortar el sync.
    """
    async with factory() as session:
        candidates = await _unexplained_disappearances(
            session, list_id=list_id, user_id=user_id, scraped_tmdb_ids=scraped_tmdb_ids
        )
    if not candidates:
        return set()
    try:
        response = await client.get(f"/{username}/films/")
    except httpx.HTTPError as exc:
        logger.warning("anti_flap.films_backstop_failed", username=username, error=str(exc))
        return set()
    slugs = [ref.slug for ref in parse_films_page(response.text)]
    if not slugs:
        return set()
    async with factory() as session:
        rows = (
            await session.execute(select(Film.tmdb_id).where(Film.letterboxd_slug.in_(slugs)))
        ).all()
    return {row[0] for row in rows}


async def reconcile_full_scrape(
    session: AsyncSession,
    *,
    list_id: int,
    user_id: int,
    scraped_films: Iterable[ResolvedFilm],
    threshold: int,
    films_page_tmdb_ids: set[int] | None = None,
) -> None:
    """Aplica anti-flap a las eliminaciones detectadas por un scrape completo.

    Para cada `list_items` que ya no aparece en `scraped_films`:
      1. Si la peli ya está en `watched_films` del owner → eliminar.
      2. Si aparece en `films_page_tmdb_ids` (página 1 de /films/; el RSS
         perdió el evento) → upsert en `watched_films` y eliminar.
      3. Si no, incrementar `pending_removal_count`; eliminar al llegar al umbral.
    Items que reaparecen tienen su contador reseteado por el orquestador.

    Los renames de slug (mismo tmdb_id) no llegan aquí — `resolve_films` los
    absorbe al matchear por tmdb_id. Un remap de TMDB id entra como item nuevo
    vía upsert y el item viejo se retira por el contador normal.
    """
    scraped_tmdb_ids = {f.tmdb_id for f in scraped_films}

    existing = (
        (await session.execute(select(ListItem).where(ListItem.list_id == list_id))).scalars().all()
    )

    for item in existing:
        if item.tmdb_id in scraped_tmdb_ids:
            continue

        watched = await session.get(WatchedFilm, (user_id, item.tmdb_id))
        if watched is not None:
            logger.info(
                "anti_flap.removed_watched",
                list_id=list_id,
                tmdb_id=item.tmdb_id,
            )
            await session.delete(item)
            continue

        if films_page_tmdb_ids and item.tmdb_id in films_page_tmdb_ids:
            logger.info(
                "anti_flap.removed_films_page",
                list_id=list_id,
                tmdb_id=item.tmdb_id,
            )
            session.add(
                WatchedFilm(
                    user_id=user_id,
                    tmdb_id=item.tmdb_id,
                    source=WatchedSource.FILMS_PAGE,
                )
            )
            await session.delete(item)
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
