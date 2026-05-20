from __future__ import annotations

from datetime import date

from watchlistarr.services.letterboxd.rss import parse_rss_feed


def test_parse_rss_feed_filters_and_extracts(rss_feed_xml: str) -> None:
    events = parse_rss_feed(rss_feed_xml)
    guids = [e.guid for e in events]
    # Solo watch + review de movies (list y tv ignorados).
    assert sorted(guids) == ["letterboxd-review-1153149850", "letterboxd-watch-1310048973"]

    watch = next(e for e in events if e.guid == "letterboxd-watch-1310048973")
    assert watch.tmdb_id == 54580
    assert watch.watched_date == date(2026, 5, 9)
    assert watch.rating is None
    assert watch.member_like is True
    assert watch.is_review is False
    assert watch.film_title == "Mondays in the Sun"
    assert watch.film_year == 2002

    review = next(e for e in events if e.guid == "letterboxd-review-1153149850")
    assert review.tmdb_id == 823219
    assert review.rating == 4.5
    assert review.member_like is True
    assert review.is_review is True


def test_parse_rss_feed_empty() -> None:
    assert parse_rss_feed("<?xml version='1.0'?><rss version='2.0'><channel/></rss>") == []


def _wrap(items: str) -> str:
    return f"""<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0"
     xmlns:letterboxd="https://letterboxd.com"
     xmlns:tmdb="https://themoviedb.org">
  <channel>
    <title>t</title>
    <link>x</link>
    <description>d</description>
    {items}
  </channel>
</rss>"""


def test_parse_rss_feed_skips_when_tmdb_movie_id_missing() -> None:
    item = """
    <item>
      <title>t</title>
      <guid isPermaLink="false">letterboxd-watch-1</guid>
      <pubDate>Sun, 10 May 2026 10:00:30 +0000</pubDate>
      <letterboxd:watchedDate>2026-05-09</letterboxd:watchedDate>
    </item>"""
    assert parse_rss_feed(_wrap(item)) == []


def test_parse_rss_feed_skips_when_watched_date_invalid() -> None:
    item = """
    <item>
      <title>t</title>
      <guid isPermaLink="false">letterboxd-watch-2</guid>
      <pubDate>Sun, 10 May 2026 10:00:30 +0000</pubDate>
      <letterboxd:watchedDate>not-a-date</letterboxd:watchedDate>
      <tmdb:movieId>42</tmdb:movieId>
    </item>"""
    assert parse_rss_feed(_wrap(item)) == []


def test_parse_rss_feed_handles_bad_rating_and_year() -> None:
    item = """
    <item>
      <title>t</title>
      <guid isPermaLink="false">letterboxd-watch-3</guid>
      <pubDate>Sun, 10 May 2026 10:00:30 +0000</pubDate>
      <letterboxd:watchedDate>2026-05-09</letterboxd:watchedDate>
      <letterboxd:filmTitle>T</letterboxd:filmTitle>
      <letterboxd:filmYear>not-a-year</letterboxd:filmYear>
      <letterboxd:memberRating>nope</letterboxd:memberRating>
      <tmdb:movieId>10</tmdb:movieId>
    </item>"""
    events = parse_rss_feed(_wrap(item))
    assert len(events) == 1
    assert events[0].rating is None
    assert events[0].film_year is None
