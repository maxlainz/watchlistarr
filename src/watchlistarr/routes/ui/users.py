from __future__ import annotations

import asyncio
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchlistarr.config import Settings, get_settings
from watchlistarr.db import get_session, get_session_factory
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

_background_tasks: set[asyncio.Task[None]] = set()


async def _initial_run_in_background(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
    scheduler: object | None,
) -> None:
    client = LetterboxdClient(settings)
    try:
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                logger.warning("initial_run.user_missing", user_id=user_id)
                return
            try:
                await run_initial_for_user(session, client, user)
                await session.commit()
            except Exception as exc:
                logger.exception("initial_run.failed", user_id=user_id, error=str(exc))
                await session.rollback()
                return
    finally:
        await client.aclose()

    if scheduler is not None and hasattr(scheduler, "sync_jobs"):
        try:
            await scheduler.sync_jobs()
        except Exception as exc:
            logger.exception("scheduler.sync_failed", error=str(exc))


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
    finally:
        await client.aclose()

    existing = (
        await session.execute(select(User).where(User.letterboxd_username == validated))
    ).scalar_one_or_none()
    if existing is not None:
        return RedirectResponse(url=f"/users/{validated}", status_code=303)

    user = User(letterboxd_username=validated)
    session.add(user)
    await session.flush()
    await session.commit()

    scheduler = getattr(request.app.state, "scheduler", None)
    task = asyncio.create_task(
        _initial_run_in_background(get_session_factory(), settings, user.id, scheduler)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("user.added", username=validated, user_id=user.id)
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
