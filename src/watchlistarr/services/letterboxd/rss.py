from __future__ import annotations

from datetime import datetime
from typing import Any

import feedparser

from watchlistarr.schemas.letterboxd import RssEvent

_ACCEPTED_PREFIXES = ("letterboxd-watch-", "letterboxd-review-")
_IGNORED_PREFIXES = ("letterboxd-list-",)


def parse_rss_feed(xml: str) -> list[RssEvent]:
    parsed = feedparser.parse(xml)
    events: list[RssEvent] = []
    for entry in parsed.entries:
        event = _parse_entry(entry)
        if event is not None:
            events.append(event)
    return events


def _parse_entry(entry: Any) -> RssEvent | None:
    guid = entry.get("id") or entry.get("guid")
    if not guid or not isinstance(guid, str):
        return None
    if guid.startswith(_IGNORED_PREFIXES):
        return None
    if not guid.startswith(_ACCEPTED_PREFIXES):
        return None

    tmdb_movie_id = entry.get("tmdb_movieid")
    if not tmdb_movie_id:
        return None
    try:
        tmdb_id = int(tmdb_movie_id)
    except (TypeError, ValueError):
        return None

    watched_date_str = entry.get("letterboxd_watcheddate")
    if not watched_date_str:
        return None
    try:
        watched_date = datetime.strptime(watched_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    rating_str = entry.get("letterboxd_memberrating")
    rating: float | None = None
    if rating_str:
        try:
            rating = float(rating_str)
        except (TypeError, ValueError):
            rating = None

    member_like = str(entry.get("letterboxd_memberlike") or "No").lower() == "yes"
    film_title = entry.get("letterboxd_filmtitle")
    film_year_raw = entry.get("letterboxd_filmyear")
    film_year: int | None = None
    if film_year_raw:
        try:
            film_year = int(film_year_raw)
        except (TypeError, ValueError):
            film_year = None

    return RssEvent(
        guid=guid,
        tmdb_id=tmdb_id,
        watched_date=watched_date,
        rating=rating,
        member_like=member_like,
        is_review=guid.startswith("letterboxd-review-"),
        film_title=film_title if isinstance(film_title, str) else None,
        film_year=film_year,
    )
