"""Backfill ``films.letterboxd_avg_rating`` para films ya en DB.

Recorre todos los films con ``letterboxd_avg_rating IS NULL`` y los
re-resuelve fetcheando la ficha de Letterboxd, donde el rating vive en el
JSON-LD ``aggregateRating.ratingValue``. Cada film necesita ~2s por el
rate-limit del LetterboxdClient.

Uso:
    uv run python scripts/backfill_ratings.py [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from watchlistarr.config import get_settings
from watchlistarr.db import dispose_engine, get_session_factory, init_engine
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.rating_backfill import backfill_missing_ratings


async def _main(limit: int | None) -> int:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        factory = get_session_factory()
        async with LetterboxdClient(settings) as client:
            enriched = await backfill_missing_ratings(factory, client, limit=limit)
        print(f"backfilled letterboxd_avg_rating en {enriched} films")
    finally:
        await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="máx films a procesar")
    args = parser.parse_args()
    return asyncio.run(_main(args.limit))


if __name__ == "__main__":
    sys.exit(main())
