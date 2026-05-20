from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def lists_index_html() -> str:
    return _read("lists_index.html")


@pytest.fixture
def watchlist_p1_html() -> str:
    return _read("watchlist_p1.html")


@pytest.fixture
def pagination_block_html() -> str:
    return _read("pagination_block.html")


@pytest.fixture
def pagination_single_html() -> str:
    return _read("pagination_single.html")


@pytest.fixture
def film_page_movie_html() -> str:
    return _read("film_page_movie.html")


@pytest.fixture
def film_page_tv_html() -> str:
    return _read("film_page_tv.html")


@pytest.fixture
def films_p1_html() -> str:
    return _read("films_p1.html")


@pytest.fixture
def rss_feed_xml() -> str:
    return _read("rss_feed.xml")
