from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import SourceType
from watchlistarr.models.list_items import ListItem
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
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    summary: list[dict[str, object]] = []
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
        list_summaries: list[dict[str, object]] = []
        for lst in lists:
            count = (
                await session.execute(
                    select(func.count(ListItem.list_id)).where(ListItem.list_id == lst.id)
                )
            ).scalar_one()
            list_summaries.append(
                {
                    "slug": lst.slug,
                    "name": lst.name,
                    "source_type": lst.source_type.value,
                    "items": count,
                    "last_sync_status": lst.last_sync_status.value,
                    "last_synced_at": lst.last_synced_at,
                }
            )
        summary.append({"user": user, "lists": list_summaries})

    recent_runs = list(
        (await session.execute(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(10)))
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"summary": summary, "runs": recent_runs, "source_types": SourceType},
    )
