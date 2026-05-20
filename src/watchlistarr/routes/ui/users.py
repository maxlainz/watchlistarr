from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import get_settings
from watchlistarr.db import get_session
from watchlistarr.models.enums import SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.scrape.initial_run import (
    UserValidationError,
    run_initial_for_user,
    validate_username,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/users")


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    return templates.TemplateResponse(request, "users/list.html", {"users": users})


@router.post("")
async def add_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form()],
) -> RedirectResponse:
    username = username.strip().lower()
    settings = get_settings()
    client = LetterboxdClient(settings)
    try:
        try:
            validated = await validate_username(client, username)
        except UserValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing = (
            await session.execute(select(User).where(User.letterboxd_username == validated))
        ).scalar_one_or_none()
        if existing is not None:
            return RedirectResponse(url=f"/users/{validated}", status_code=303)
        user = User(letterboxd_username=validated)
        session.add(user)
        await session.flush()
        await run_initial_for_user(session, client, user)
        await session.commit()
    finally:
        await client.aclose()

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return RedirectResponse(url=f"/users/{validated}", status_code=303)


@router.post("/{username}/delete")
async def delete_user(
    username: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    await session.delete(user)
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return RedirectResponse(url="/users", status_code=303)


@router.get("/{username}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    username: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    lists = list(
        (await session.execute(select(ListModel).where(ListModel.user_id == user.id)))
        .scalars()
        .all()
    )
    watchlists = [lst for lst in lists if lst.source_type is SourceType.WATCHLIST]
    custom = [lst for lst in lists if lst.source_type is SourceType.LIST]
    return templates.TemplateResponse(
        request,
        "users/detail.html",
        {"user": user, "watchlists": watchlists, "custom": custom},
    )


@router.post("/{username}/lists/{list_id}/toggle")
async def toggle_list(
    username: str,
    list_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    lst = await session.get(ListModel, list_id)
    if lst is None or lst.user_id != user.id:
        raise HTTPException(status_code=404)
    lst.enabled = not lst.enabled
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return RedirectResponse(url=f"/users/{username}", status_code=303)
