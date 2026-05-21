"""Backfill ``films.imdb_id`` para films ya en DB.

Recorre todos los films con ``imdb_id IS NULL`` y los re-resuelve fetcheando
la ficha de Letterboxd. Cada film necesita ~2s por el rate-limit del
LetterboxdClient.

Uso:
    uv run python scripts/backfill_imdb.py [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from watchlistarr.config import get_settings
from watchlistarr.db import dispose_engine, get_session_factory, init_engine
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.imdb_backfill import backfill_missing_imdb_ids


async def _main(limit: int | None) -> int:
    settings = get_settings()
    init_engine(settings.database_url)
    try:
        factory = get_session_factory()
        async with LetterboxdClient(settings) as client:
            enriched = await backfill_missing_imdb_ids(factory, client, limit=limit)
        print(f"backfilled imdb_id en {enriched} films")
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
