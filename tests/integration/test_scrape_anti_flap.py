from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.enums import SourceType, WatchedSource
from watchlistarr.models.films import Film
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.models.watched_films import WatchedFilm
from watchlistarr.services.scrape.anti_flap import reconcile_full_scrape
from watchlistarr.services.scrape.film_resolver import ResolvedFilm


async def _make_user_list(session: AsyncSession) -> ListModel:
    user = User(letterboxd_username="alice")
    session.add(user)
    await session.flush()
    lst = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="Watchlist",
        enabled=True,
    )
    session.add(lst)
    await session.flush()
    return lst


async def _add_item(
    session: AsyncSession, lst: ListModel, tmdb_id: int, slug: str, title: str, year: int
) -> ListItem:
    session.add(Film(tmdb_id=tmdb_id, letterboxd_slug=slug, title=title, year=year))
    await session.flush()
    item = ListItem(list_id=lst.id, tmdb_id=tmdb_id, position=0)
    session.add(item)
    await session.flush()
    return item


async def test_anti_flap_removes_immediately_when_watched(session: AsyncSession) -> None:
    lst = await _make_user_list(session)
    await _add_item(session, lst, 100, "old", "Old", 2010)
    session.add(WatchedFilm(user_id=lst.user_id, tmdb_id=100, source=WatchedSource.RSS))
    await session.flush()

    await reconcile_full_scrape(
        session, list_id=lst.id, user_id=lst.user_id, scraped_films=[], threshold=3
    )
    remaining = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    assert remaining == []


async def test_anti_flap_tmdb_remap_goes_through_counter(session: AsyncSession) -> None:
    """Remap de TMDB id (mismo título/año, distinto tmdb): el item viejo pasa
    por el contador normal, sin tocar slugs (regresión: la rama de rename
    reasignaba el slug del film nuevo al viejo → IntegrityError por UNIQUE)."""
    lst = await _make_user_list(session)
    await _add_item(session, lst, 200, "old-slug", "Foo", 2020)
    # En producción resolve_films ya persistió el film nuevo con el slug nuevo.
    session.add(Film(tmdb_id=999, letterboxd_slug="new-slug", title="Foo", year=2020))
    await session.flush()
    remapped_film = ResolvedFilm(
        tmdb_id=999, letterboxd_slug="new-slug", title="Foo", year=2020, imdb_id=None
    )

    await reconcile_full_scrape(
        session,
        list_id=lst.id,
        user_id=lst.user_id,
        scraped_films=[remapped_film],
        threshold=3,
    )
    await session.flush()
    item = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().one()
    )
    assert item.tmdb_id == 200
    assert item.pending_removal_count == 1
    film200 = await session.get(Film, 200)
    assert film200 is not None
    assert film200.letterboxd_slug == "old-slug"


async def test_anti_flap_films_page_backstop_marks_watched_and_removes(
    session: AsyncSession,
) -> None:
    lst = await _make_user_list(session)
    await _add_item(session, lst, 300, "seen", "Seen", 2018)

    await reconcile_full_scrape(
        session,
        list_id=lst.id,
        user_id=lst.user_id,
        scraped_films=[],
        threshold=3,
        films_page_tmdb_ids={300},
    )
    remaining = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    assert remaining == []
    watched = await session.get(WatchedFilm, (lst.user_id, 300))
    assert watched is not None
    assert watched.source is WatchedSource.FILMS_PAGE


async def test_anti_flap_films_page_miss_increments_counter(session: AsyncSession) -> None:
    lst = await _make_user_list(session)
    await _add_item(session, lst, 400, "missing", "Missing", 2019)

    await reconcile_full_scrape(
        session,
        list_id=lst.id,
        user_id=lst.user_id,
        scraped_films=[],
        threshold=3,
        films_page_tmdb_ids={111},
    )
    item = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().one()
    )
    assert item.pending_removal_count == 1
    assert await session.get(WatchedFilm, (lst.user_id, 400)) is None


async def test_anti_flap_increments_then_removes_at_threshold(session: AsyncSession) -> None:
    lst = await _make_user_list(session)
    await _add_item(session, lst, 300, "ghost", "Ghost", 2015)

    await reconcile_full_scrape(
        session, list_id=lst.id, user_id=lst.user_id, scraped_films=[], threshold=3
    )
    item = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().one()
    )
    assert item.pending_removal_count == 1

    await reconcile_full_scrape(
        session, list_id=lst.id, user_id=lst.user_id, scraped_films=[], threshold=3
    )
    item = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().one()
    )
    assert item.pending_removal_count == 2

    await reconcile_full_scrape(
        session, list_id=lst.id, user_id=lst.user_id, scraped_films=[], threshold=3
    )
    remaining = (
        (await session.execute(select(ListItem).where(ListItem.list_id == lst.id))).scalars().all()
    )
    assert remaining == []
