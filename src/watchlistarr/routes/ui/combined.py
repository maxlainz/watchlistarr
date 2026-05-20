from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import CombinedKind
from watchlistarr.models.sublists import Sublist
from watchlistarr.routes.ui import templates
from watchlistarr.services.combined import combined_watchlist_tmdb_ids

router = APIRouter()


@router.get("/combined", response_class=HTMLResponse)
async def combined_view(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    raw_counts: dict[str, int] = {}
    for kind in CombinedKind:
        tmdb_ids = await combined_watchlist_tmdb_ids(session, kind)
        raw_counts[kind.value] = len(tmdb_ids)

    sublists = list(
        (await session.execute(select(Sublist).where(Sublist.parent_combined_kind.is_not(None))))
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        request,
        "combined.html",
        {"raw_counts": raw_counts, "sublists": sublists},
    )
