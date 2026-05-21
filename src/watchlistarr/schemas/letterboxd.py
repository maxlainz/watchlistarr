from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DiscoveredList:
    letterboxd_list_id: str
    slug: str
    name: str
    film_count: int


@dataclass(frozen=True, slots=True)
class ListItemRef:
    slug: str
    name: str | None


@dataclass(frozen=True, slots=True)
class ListPage:
    items: list[ListItemRef]
    total_pages: int


@dataclass(frozen=True, slots=True)
class FilmPageData:
    slug: str
    tmdb_id: int | None
    tmdb_type: str
    title: str | None
    year: int | None
    imdb_id: str | None
    letterboxd_avg_rating: float | None


@dataclass(frozen=True, slots=True)
class RssEvent:
    guid: str
    tmdb_id: int
    watched_date: date
    rating: float | None
    member_like: bool
    is_review: bool
    film_title: str | None
    film_year: int | None


@dataclass(frozen=True, slots=True)
class UserProfile:
    username: str
    display_name: str | None
    exists: bool
