from __future__ import annotations

from bs4 import BeautifulSoup

from watchlistarr.schemas.letterboxd import ListItemRef


def parse_films_page(html: str) -> list[ListItemRef]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItemRef] = []
    for li in soup.select("li.griditem"):
        div = li.select_one("div.react-component[data-item-slug]")
        if div is None:
            continue
        slug = div.get("data-item-slug")
        if not slug:
            continue
        name = div.get("data-item-name")
        items.append(ListItemRef(slug=str(slug), name=str(name) if name else None))
    return items
