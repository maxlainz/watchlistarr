from __future__ import annotations

from datetime import timedelta

from watchlistarr.config import Settings
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services import intervals


def _env() -> Settings:
    return Settings(letterboxd_offline=True)


def test_user_rss_falls_back_to_env_when_none() -> None:
    user = User(letterboxd_username="alice")
    env = _env()
    assert intervals.user_rss_interval(user, env) == env.rss_interval


def test_user_rss_uses_override_when_set() -> None:
    user = User(letterboxd_username="alice", rss_interval=timedelta(seconds=300))
    env = _env()
    assert intervals.user_rss_interval(user, env) == timedelta(seconds=300)


def test_list_full_falls_back_to_env() -> None:
    lst = ListModel(
        user_id=1, source_type=SourceType.LIST, slug="favs", name="F", letterboxd_list_id="1"
    )
    env = _env()
    assert intervals.list_full(lst, env) == env.lists_full_interval


def test_list_full_uses_override() -> None:
    lst = ListModel(
        user_id=1,
        source_type=SourceType.LIST,
        slug="favs",
        name="F",
        letterboxd_list_id="1",
        lists_full_interval=timedelta(seconds=999),
    )
    env = _env()
    assert intervals.list_full(lst, env) == timedelta(seconds=999)


def test_list_flap_threshold_zero_override_is_respected() -> None:
    # Aunque 0 es falsy, `flap_confirm_scrapes` usa `is None`, no `or`.
    lst = ListModel(
        user_id=1,
        source_type=SourceType.LIST,
        slug="favs",
        name="F",
        letterboxd_list_id="1",
        flap_confirm_scrapes=0,
    )
    env = _env()
    assert intervals.list_flap_threshold(lst, env) == 0


def test_list_flap_threshold_falls_back_when_none() -> None:
    lst = ListModel(
        user_id=1, source_type=SourceType.LIST, slug="favs", name="F", letterboxd_list_id="1"
    )
    env = _env()
    assert intervals.list_flap_threshold(lst, env) == env.flap_confirm_scrapes
