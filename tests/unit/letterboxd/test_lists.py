from __future__ import annotations

from watchlistarr.services.letterboxd.lists import (
    parse_list_items,
    parse_lists_index,
    parse_total_pages,
)


def test_parse_lists_index_basic(lists_index_html: str) -> None:
    result = parse_lists_index(lists_index_html)
    assert len(result) == 3
    favs = next(item for item in result if item.slug == "favs")
    assert favs.letterboxd_list_id == "73057123"
    assert favs.name == "Favs"
    assert favs.film_count == 5

    must_watch = next(item for item in result if item.slug == "2010s-must-watch")
    assert must_watch.film_count == 128

    empty = next(item for item in result if item.slug == "empty-list")
    assert empty.film_count == 0


def test_parse_list_items_returns_slugs(watchlist_p1_html: str) -> None:
    items = parse_list_items(watchlist_p1_html)
    slugs = [item.slug for item in items]
    assert slugs == ["3-faces", "parasite-2019", "anatomy-of-a-fall"]
    assert items[0].name == "3 Faces (2018)"


def test_parse_total_pages_with_block(pagination_block_html: str) -> None:
    assert parse_total_pages(pagination_block_html) == 23


def test_parse_total_pages_without_block(pagination_single_html: str) -> None:
    assert parse_total_pages(pagination_single_html) == 1


def test_parse_lists_index_empty_html() -> None:
    assert parse_lists_index("<html><body></body></html>") == []


def test_parse_list_items_empty_html() -> None:
    assert parse_list_items("<html><body></body></html>") == []


def test_parse_lists_index_skips_article_without_link() -> None:
    html = """
    <html><body>
      <article class="list-summary" data-film-list-id="1"></article>
    </body></html>
    """
    assert parse_lists_index(html) == []


def test_parse_lists_index_skips_when_href_malformed() -> None:
    html = """
    <html><body>
      <article class="list-summary" data-film-list-id="1">
        <h2 class="name"><a href="/maxlainz/profile/">Wrong</a></h2>
      </article>
    </body></html>
    """
    assert parse_lists_index(html) == []


def test_parse_list_items_skips_div_with_empty_slug() -> None:
    html = """
    <html><body>
      <div class="react-component" data-item-slug="" data-item-name="No slug"></div>
    </body></html>
    """
    assert parse_list_items(html) == []
