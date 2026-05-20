from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    LIST = "list"
    WATCHLIST = "watchlist"


class CombinedKind(StrEnum):
    UNION = "union"
    INTERSECTION = "intersection"
    UNION_UNWATCHED = "union-unwatched"


class ScrapeSource(StrEnum):
    LIST = "list"
    WATCHLIST = "watchlist"
    FILMS = "films"
    RSS = "rss"
    DISCOVERY = "discovery"
    ROTATION = "rotation"


class ScrapeStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    RUNNING = "running"


class SyncStatus(StrEnum):
    NEVER = "never"
    SUCCESS = "success"
    ERROR = "error"


class WatchedSource(StrEnum):
    RSS = "rss"
    FILMS_PAGE = "films-page"


class SortOrder(StrEnum):
    LETTERBOXD = "letterboxd"
    RANDOM = "random"
    REVERSE = "reverse"
