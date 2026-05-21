from __future__ import annotations

from watchlistarr.services.letterboxd.film_page import parse_film_page


def test_parse_film_page_movie(film_page_movie_html: str) -> None:
    data = parse_film_page(film_page_movie_html, slug="parasite-2019")
    assert data.tmdb_id == 496243
    assert data.tmdb_type == "movie"
    assert data.title == "Parasite"
    assert data.year == 2019
    assert data.imdb_id == "tt6751668"
    assert data.slug == "parasite-2019"


def test_parse_film_page_tv(film_page_tv_html: str) -> None:
    data = parse_film_page(film_page_tv_html, slug="severance")
    assert data.tmdb_type == "tv"
    # tmdb_id sí está en TV pages también, pero el caller filtra por tmdb_type.
    assert data.tmdb_id == 95396


def test_parse_film_page_garbage_returns_empty_data() -> None:
    data = parse_film_page("not html", slug="x")
    assert data.tmdb_id is None
    assert data.tmdb_type == ""
    assert data.imdb_id is None
    assert data.slug == "x"


def test_parse_film_page_missing_tmdb_id() -> None:
    html = """
    <html><body data-tmdb-type="movie"></body></html>
    """
    data = parse_film_page(html, slug="ghost")
    assert data.tmdb_id is None
    assert data.tmdb_type == "movie"


def test_parse_film_page_og_title_without_year() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="Untitled Movie"></head>
      <body data-tmdb-type="movie" data-tmdb-id="1"></body>
    </html>
    """
    data = parse_film_page(html, slug="untitled")
    assert data.title == "Untitled Movie"
    assert data.year is None


def test_parse_film_page_no_imdb_link() -> None:
    html = '<html><body data-tmdb-type="movie" data-tmdb-id="1"></body></html>'
    data = parse_film_page(html, slug="no-imdb")
    assert data.imdb_id is None


def test_parse_film_page_imdb_id_https() -> None:
    html = """
    <html><body data-tmdb-type="movie" data-tmdb-id="1">
      <a href="https://www.imdb.com/title/tt1234567/">IMDb</a>
    </body></html>
    """
    data = parse_film_page(html, slug="https-imdb")
    assert data.imdb_id == "tt1234567"
