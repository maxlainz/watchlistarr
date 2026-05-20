from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import CombinedKind, SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.sublists import Sublist
from watchlistarr.models.users import User
from watchlistarr.schemas.radarr import RadarrItem
from watchlistarr.services.combined import combined_watchlist_tmdb_ids
from watchlistarr.services.radarr import (
    compute_etag,
    render_payload,
    serialize_combined,
    serialize_list,
    serialize_sublist,
)

RESERVED_USERS: frozenset[str] = frozenset({"all", "api", "admin", "static", "health", "_"})

router = APIRouter()


def _respond(items: list[RadarrItem], request: Request) -> Response:
    payload = render_payload(items)
    etag = compute_etag(payload)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"ETag": etag},
    )


@router.get("/all/watchlist/{combo}/")
async def combined_watchlist_endpoint(
    combo: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    try:
        kind = CombinedKind(combo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="combinada desconocida") from exc
    tmdb_ids = await combined_watchlist_tmdb_ids(session, kind)
    items = await serialize_combined(session, tmdb_ids)
    return _respond(items, request)


@router.get("/all/{slug}/")
async def combined_sublist_endpoint(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    sublist = (
        await session.execute(
            select(Sublist).where(Sublist.slug == slug, Sublist.parent_combined_kind.is_not(None))
        )
    ).scalar_one_or_none()
    if sublist is None:
        raise HTTPException(status_code=404, detail="sublista combinada no existe")
    items = await serialize_sublist(session, sublist.id)
    return _respond(items, request)


@router.get("/{username}/watchlist/")
async def user_watchlist_endpoint(
    username: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if username in RESERVED_USERS:
        raise HTTPException(status_code=404)
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user no existe")
    watchlist = (
        await session.execute(
            select(ListModel).where(
                ListModel.user_id == user.id,
                ListModel.source_type == SourceType.WATCHLIST,
            )
        )
    ).scalar_one_or_none()
    if watchlist is None:
        raise HTTPException(status_code=404, detail="watchlist no existe")
    items = await serialize_list(session, watchlist.id)
    return _respond(items, request)


@router.get("/{username}/{slug}/")
async def user_slug_endpoint(
    username: str,
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if username in RESERVED_USERS:
        raise HTTPException(status_code=404)
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user no existe")

    list_row = (
        await session.execute(
            select(ListModel).where(ListModel.user_id == user.id, ListModel.slug == slug)
        )
    ).scalar_one_or_none()
    if list_row is not None:
        items = await serialize_list(session, list_row.id)
        return _respond(items, request)

    sublist = (
        await session.execute(
            select(Sublist).where(Sublist.user_id == user.id, Sublist.slug == slug)
        )
    ).scalar_one_or_none()
    if sublist is not None:
        items = await serialize_sublist(session, sublist.id)
        return _respond(items, request)

    raise HTTPException(status_code=404, detail="slug no existe para el user")
