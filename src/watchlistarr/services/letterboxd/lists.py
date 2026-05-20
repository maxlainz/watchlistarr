from __future__ import annotations

import re

from bs4 import BeautifulSoup

from watchlistarr.schemas.letterboxd import DiscoveredList, ListItemRef

_PAGE_RE = re.compile(r"/page/(\d+)/?$")


def parse_lists_index(html: str) -> list[DiscoveredList]:
    soup = BeautifulSoup(html, "lxml")
    results: list[DiscoveredList] = []
    for article in soup.select("article.list-summary[data-film-list-id]"):
        list_id = article.get("data-film-list-id")
        link_el = article.select_one("h2.name a")
        if not list_id or not link_el:
            continue
        href = link_el.get("href") or ""
        parts = str(href).strip("/").split("/")
        if len(parts) < 3 or parts[1] != "list":
            continue
        slug = parts[2]
        name = link_el.get_text(strip=True)
        count_el = article.select_one(".content-reactions-strip .value")
        film_count = 0
        if count_el is not None:
            digits = "".join(ch for ch in count_el.get_text(strip=True) if ch.isdigit())
            film_count = int(digits) if digits else 0
        results.append(
            DiscoveredList(
                letterboxd_list_id=str(list_id),
                slug=slug,
                name=name,
                film_count=film_count,
            )
        )
    return results


def parse_list_items(html: str) -> list[ListItemRef]:
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItemRef] = []
    for div in soup.select("div.react-component[data-item-slug]"):
        slug = div.get("data-item-slug")
        if not slug:
            continue
        name = div.get("data-item-name")
        items.append(ListItemRef(slug=str(slug), name=str(name) if name else None))
    return items


def parse_total_pages(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    pagination = soup.select_one("div.pagination")
    if pagination is None:
        return 1
    max_page = 1
    for anchor in pagination.select("a"):
        href = anchor.get("href") or ""
        match = _PAGE_RE.search(str(href))
        if match:
            max_page = max(max_page, int(match.group(1)))
    return max_page
