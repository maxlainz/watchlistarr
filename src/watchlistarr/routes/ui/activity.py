from __future__ import annotations

import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import ScrapeSource, ScrapeStatus
from watchlistarr.models.scrape_runs import ScrapeRun
from watchlistarr.routes.ui import templates

router = APIRouter()


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    source: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> HTMLResponse:
    stmt = select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit)
    if source:
        with contextlib.suppress(ValueError):
            stmt = stmt.where(ScrapeRun.source == ScrapeSource(source))
    if status:
        with contextlib.suppress(ValueError):
            stmt = stmt.where(ScrapeRun.status == ScrapeStatus(status))
    runs = list((await session.execute(stmt)).scalars().all())
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "runs": runs,
            "sources": [s.value for s in ScrapeSource],
            "statuses": [s.value for s in ScrapeStatus],
            "filter_source": source,
            "filter_status": status,
        },
    )
