from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import get_settings
from watchlistarr.db import get_session
from watchlistarr.models.enums import SourceType
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates

router = APIRouter()


def _td_seconds(td: object | None) -> int | None:
    if td is None:
        return None
    return int(td.total_seconds())  # type: ignore[attr-defined]


def _td_from_form(seconds: int | None) -> object | None:
    if seconds is None or seconds <= 0:
        return None
    from datetime import timedelta

    return timedelta(seconds=seconds)


def _int_from_form(value: int | None) -> int | None:
    if value is None or value <= 0:
        return None
    return value


def _radarr_url(user: User, lst: ListModel) -> str:
    return f"/{user.letterboxd_username}/{lst.slug}/"


@router.get("/lists-view", response_class=HTMLResponse)
async def lists_view(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    env = get_settings()
    groups: list[dict[str, object]] = []
    for user in users:
        lists = list(
            (
                await session.execute(
                    select(ListModel).where(
                        ListModel.user_id == user.id, ListModel.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        # watchlist first
        lists.sort(
            key=lambda lst: (0 if lst.source_type is SourceType.WATCHLIST else 1, lst.name.lower())
        )
        rows: list[dict[str, object]] = []
        for lst in lists:
            items_count = (
                await session.execute(
                    select(func.count(ListItem.list_id)).where(ListItem.list_id == lst.id)
                )
            ).scalar_one()
            rows.append(
                {
                    "list": lst,
                    "items": items_count,
                    "url": _radarr_url(user, lst),
                    "is_watchlist": lst.source_type is SourceType.WATCHLIST,
                    "advanced": {
                        "lists_incremental_interval": (
                            _td_seconds(lst.lists_incremental_interval),
                            int(env.lists_incremental_interval.total_seconds()),
                        ),
                        "lists_full_interval": (
                            _td_seconds(lst.lists_full_interval),
                            int(env.lists_full_interval.total_seconds()),
                        ),
                        "flap_confirm_scrapes": (
                            lst.flap_confirm_scrapes,
                            env.flap_confirm_scrapes,
                        ),
                    },
                }
            )
        groups.append({"user": user, "rows": rows})
    return templates.TemplateResponse(request, "lists/index.html", {"groups": groups})


@router.post("/lists-view/{username}/{list_slug}/settings")
async def update_list_settings(
    request: Request,
    username: str,
    list_slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    lists_incremental_interval: Annotated[int | None, Form()] = None,
    lists_full_interval: Annotated[int | None, Form()] = None,
    flap_confirm_scrapes: Annotated[int | None, Form()] = None,
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    lst = (
        await session.execute(
            select(ListModel).where(ListModel.user_id == user.id, ListModel.slug == list_slug)
        )
    ).scalar_one_or_none()
    if lst is None:
        raise HTTPException(status_code=404)
    lst.lists_incremental_interval = _td_from_form(lists_incremental_interval)  # type: ignore[assignment]
    lst.lists_full_interval = _td_from_form(lists_full_interval)  # type: ignore[assignment]
    lst.flap_confirm_scrapes = _int_from_form(flap_confirm_scrapes)
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return RedirectResponse(url="/lists-view", status_code=303)
