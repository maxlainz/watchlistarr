from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import CombinedKind, SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.sublists import Sublist
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates

router = APIRouter()


@router.get("/endpoints", response_class=HTMLResponse)
async def endpoints_page(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    parent_endpoints: list[dict[str, str]] = []
    sublist_endpoints: list[dict[str, str]] = []
    combined_endpoints: list[dict[str, str]] = [
        {"label": f"combinada {k.value}", "url": f"/all/watchlist/{k.value}/"} for k in CombinedKind
    ]
    combined_sublist_endpoints: list[dict[str, str]] = []

    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
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
        for lst in lists:
            label = "watchlist" if lst.source_type is SourceType.WATCHLIST else f"lista {lst.name}"
            parent_endpoints.append(
                {
                    "label": f"{user.letterboxd_username} · {label}",
                    "url": f"/{user.letterboxd_username}/{lst.slug}/",
                }
            )
        subs = list(
            (await session.execute(select(Sublist).where(Sublist.user_id == user.id)))
            .scalars()
            .all()
        )
        for sub in subs:
            sublist_endpoints.append(
                {
                    "label": f"{user.letterboxd_username} · sublista {sub.name}",
                    "url": f"/{user.letterboxd_username}/{sub.slug}/",
                }
            )

    combined_subs = list(
        (await session.execute(select(Sublist).where(Sublist.parent_combined_kind.is_not(None))))
        .scalars()
        .all()
    )
    for sub in combined_subs:
        combined_sublist_endpoints.append(
            {"label": f"sublista combinada {sub.name}", "url": f"/all/{sub.slug}/"}
        )

    return templates.TemplateResponse(
        request,
        "endpoints.html",
        {
            "parent": parent_endpoints,
            "sublists": sublist_endpoints,
            "combined": combined_endpoints,
            "combined_sublists": combined_sublist_endpoints,
        },
    )
