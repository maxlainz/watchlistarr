from __future__ import annotations

import re

from bs4 import BeautifulSoup

from watchlistarr.schemas.letterboxd import FilmPageData

_TITLE_YEAR_RE = re.compile(r"^(.*?)\s*\((\d{4})\)\s*$")
_IMDB_ID_RE = re.compile(r"imdb\.com/title/(tt\d{7,10})")


def parse_film_page(html: str, *, slug: str) -> FilmPageData:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body is None:
        raise ValueError(f"film page sin <body> para slug={slug}")
    tmdb_id_raw = body.get("data-tmdb-id")  # type: ignore[union-attr]
    tmdb_type = str(body.get("data-tmdb-type") or "")  # type: ignore[union-attr]
    tmdb_id: int | None = None
    if tmdb_id_raw and str(tmdb_id_raw).isdigit():
        tmdb_id = int(str(tmdb_id_raw))

    title: str | None = None
    year: int | None = None
    og_title = soup.find("meta", property="og:title")
    if og_title is not None:
        content = og_title.get("content")  # type: ignore[union-attr]
        if content:
            match = _TITLE_YEAR_RE.match(str(content))
            if match:
                title = match.group(1).strip()
                year = int(match.group(2))
            else:
                title = str(content).strip()

    imdb_id: str | None = None
    imdb_match = _IMDB_ID_RE.search(html)
    if imdb_match:
        imdb_id = imdb_match.group(1)

    return FilmPageData(
        slug=slug,
        tmdb_id=tmdb_id,
        tmdb_type=tmdb_type,
        title=title,
        year=year,
        imdb_id=imdb_id,
    )
