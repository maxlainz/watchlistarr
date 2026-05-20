from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.schemas.radarr import RadarrItem
from watchlistarr.services.radarr import (
    compute_etag,
    render_payload,
    serialize_custom_list,
    serialize_list,
)

RESERVED_USERS: frozenset[str] = frozenset(
    {"all", "api", "admin", "static", "health", "_", "lists"}
)

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


@router.get("/lists/{slug}/")
async def custom_list_endpoint(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    custom_list = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if custom_list is None:
        raise HTTPException(status_code=404, detail="custom list does not exist")
    items = await serialize_custom_list(session, custom_list.id)
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
        raise HTTPException(status_code=404, detail="user not found")
    watchlist = (
        await session.execute(
            select(ListModel).where(
                ListModel.user_id == user.id,
                ListModel.source_type == SourceType.WATCHLIST,
            )
        )
    ).scalar_one_or_none()
    if watchlist is None:
        raise HTTPException(status_code=404, detail="watchlist not found")
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
        raise HTTPException(status_code=404, detail="user not found")
    list_row = (
        await session.execute(
            select(ListModel).where(ListModel.user_id == user.id, ListModel.slug == slug)
        )
    ).scalar_one_or_none()
    if list_row is None:
        raise HTTPException(status_code=404, detail="slug not found for user")
    items = await serialize_list(session, list_row.id)
    return _respond(items, request)
