from __future__ import annotations

from datetime import timedelta

from watchlistarr.config import Settings
from watchlistarr.models.lists import List
from watchlistarr.models.users import User


def user_rss_interval(user: User, env: Settings) -> timedelta:
    return user.rss_interval or env.rss_interval


def user_watchlist_incremental(user: User, env: Settings) -> timedelta:
    return user.watchlist_incremental_interval or env.watchlist_incremental_interval


def user_watchlist_full(user: User, env: Settings) -> timedelta:
    return user.watchlist_full_interval or env.watchlist_full_interval


def user_films_backstop(user: User, env: Settings) -> timedelta:
    return user.films_backstop_interval or env.films_backstop_interval


def user_discovery(user: User, env: Settings) -> timedelta:
    return user.discovery_interval or env.discovery_interval


def list_incremental(lst: List, env: Settings) -> timedelta:
    return lst.lists_incremental_interval or env.lists_incremental_interval


def list_full(lst: List, env: Settings) -> timedelta:
    return lst.lists_full_interval or env.lists_full_interval


def list_flap_threshold(lst: List, env: Settings) -> int:
    if lst.flap_confirm_scrapes is None:
        return env.flap_confirm_scrapes
    return lst.flap_confirm_scrapes
