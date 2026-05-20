from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.base import utcnow
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import ScrapeStatus
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.scrape_runs import ScrapeRun
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    users_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    lists_count = (
        await session.execute(select(func.count(ListModel.id)).where(ListModel.enabled.is_(True)))
    ).scalar_one()
    custom_count = (
        await session.execute(
            select(func.count(CustomList.id)).where(CustomList.enabled.is_(True))
        )
    ).scalar_one()

    last_success = (
        await session.execute(
            select(func.max(ScrapeRun.ended_at)).where(
                ScrapeRun.status == ScrapeStatus.SUCCESS
            )
        )
    ).scalar_one()

    one_hour_ago = utcnow() - timedelta(hours=1)
    recent_errors = (
        await session.execute(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == ScrapeStatus.ERROR, ScrapeRun.started_at >= one_hour_ago
            )
        )
    ).scalar_one()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "users_count": users_count,
            "lists_count": lists_count,
            "custom_count": custom_count,
            "last_success": last_success,
            "recent_errors": recent_errors,
        },
    )
