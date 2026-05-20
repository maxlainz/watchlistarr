from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from watchlistarr.routes.ui import templates
from watchlistarr.services.log_buffer import get_buffer

router = APIRouter()


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(
    request: Request,
    level: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    buf = get_buffer()
    lines = buf.snapshot()
    if level:
        wanted = level.upper()
        lines = [line for line in lines if line.level == wanted]
    latest_seq = buf.latest_seq()
    return templates.TemplateResponse(
        request,
        "activity.html",
        {
            "lines": lines,
            "latest_seq": latest_seq,
            "level": level,
            "levels": ["DEBUG", "INFO", "WARNING", "ERROR"],
        },
    )


@router.get("/activity/tail", response_class=HTMLResponse)
async def activity_tail(
    request: Request,
    since: Annotated[int, Query(ge=0)] = 0,
    level: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    buf = get_buffer()
    lines = buf.snapshot(since=since)
    if level:
        wanted = level.upper()
        lines = [line for line in lines if line.level == wanted]
    latest_seq = buf.latest_seq() if lines == [] else lines[-1].seq
    return templates.TemplateResponse(
        request,
        "activity/tail_fragment.html",
        {"lines": lines, "latest_seq": latest_seq, "level": level or ""},
    )


@router.get("/activity/download")
async def activity_download() -> PlainTextResponse:
    return PlainTextResponse(
        get_buffer().dump_text(), headers={"Content-Disposition": "attachment; filename=watchlistarr.log"}
    )
