from __future__ import annotations

from watchlistarr.services.letterboxd.films import parse_films_page


def test_parse_films_page_extracts_slugs(films_p1_html: str) -> None:
    items = parse_films_page(films_p1_html)
    slugs = [item.slug for item in items]
    assert slugs == ["one-battle-after-another", "mondays-in-the-sun", "flow-2024"]


def test_parse_films_page_empty() -> None:
    assert parse_films_page("<html><body></body></html>") == []


def test_parse_films_page_skips_li_without_react_component() -> None:
    html = """
    <html><body>
      <li class="griditem"><span>no component</span></li>
    </body></html>
    """
    assert parse_films_page(html) == []


def test_parse_films_page_skips_div_with_empty_slug() -> None:
    html = """
    <html><body>
      <li class="griditem">
        <div class="react-component" data-item-slug=""></div>
      </li>
    </body></html>
    """
    assert parse_films_page(html) == []
