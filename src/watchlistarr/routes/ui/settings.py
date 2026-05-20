from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.routes.ui import templates
from watchlistarr.services.settings import (
    DURATION_KEYS,
    INT_KEYS,
    get_duration,
    get_int,
    set_value,
)

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    duration_values: dict[str, int] = {}
    for key in DURATION_KEYS:
        td = await get_duration(session, key)
        duration_values[key] = int(td.total_seconds())
    int_values = {key: await get_int(session, key) for key in INT_KEYS}
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "durations": duration_values,
            "ints": int_values,
        },
    )


@router.post("/settings")
async def update_settings(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    rss_interval: Annotated[int, Form()],
    watchlist_incremental_interval: Annotated[int, Form()],
    watchlist_full_interval: Annotated[int, Form()],
    lists_incremental_interval: Annotated[int, Form()],
    lists_full_interval: Annotated[int, Form()],
    films_backstop_interval: Annotated[int, Form()],
    discovery_interval: Annotated[int, Form()],
    rotation_tick_interval: Annotated[int, Form()],
    flap_confirm_scrapes: Annotated[int, Form()],
) -> RedirectResponse:
    durations = {
        "rss_interval": rss_interval,
        "watchlist_incremental_interval": watchlist_incremental_interval,
        "watchlist_full_interval": watchlist_full_interval,
        "lists_incremental_interval": lists_incremental_interval,
        "lists_full_interval": lists_full_interval,
        "films_backstop_interval": films_backstop_interval,
        "discovery_interval": discovery_interval,
        "rotation_tick_interval": rotation_tick_interval,
    }
    for key, seconds in durations.items():
        await set_value(session, key, timedelta(seconds=max(1, seconds)))
    await set_value(session, "flap_confirm_scrapes", max(1, flap_confirm_scrapes))
    await session.commit()

    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return RedirectResponse(url="/settings", status_code=303)
