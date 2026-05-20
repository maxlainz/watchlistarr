from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.custom_list_excluded_watchers import CustomListExcludedWatcher
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import CombinationOp, SortOrder, SourceRole, SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates
from watchlistarr.services.custom_lists import (
    describe_sources,
    init_items,
    recalculate,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/custom-lists")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


async def _all_sources(session: AsyncSession) -> list[dict[str, object]]:
    """Lists available as sources: watchlists + public lists, grouped by user."""
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    groups: list[dict[str, object]] = []
    for user in users:
        lists = list(
            (await session.execute(select(ListModel).where(ListModel.user_id == user.id)))
            .scalars()
            .all()
        )
        lists.sort(
            key=lambda lst: (0 if lst.source_type is SourceType.WATCHLIST else 1, lst.name.lower())
        )
        if not lists:
            continue
        groups.append(
            {
                "user": user,
                "lists": [
                    {
                        "id": lst.id,
                        "label": (
                            "Watchlist"
                            if lst.source_type is SourceType.WATCHLIST
                            else lst.name
                        ),
                        "slug": lst.slug,
                    }
                    for lst in lists
                ],
            }
        )
    return groups


@router.get("", response_class=HTMLResponse)
async def index(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    custom_lists = list(
        (await session.execute(select(CustomList).order_by(CustomList.name))).scalars().all()
    )
    rows: list[dict[str, object]] = []
    for cl in custom_lists:
        summary = await describe_sources(session, cl)
        items_count = len(cl.items) if cl.items else 0
        if items_count == 0:
            # cl.items may not be loaded; re-fetch count
            from sqlalchemy import func

            from watchlistarr.models.custom_list_items import CustomListItem

            items_count = (
                await session.execute(
                    select(func.count(CustomListItem.custom_list_id)).where(
                        CustomListItem.custom_list_id == cl.id
                    )
                )
            ).scalar_one()
        rows.append(
            {
                "custom_list": cl,
                "summary": summary,
                "items_count": items_count,
                "url": f"/lists/{cl.slug}/",
            }
        )
    return templates.TemplateResponse(
        request, "custom_lists/index.html", {"rows": rows}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_form(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    groups = await _all_sources(session)
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    return templates.TemplateResponse(
        request,
        "custom_lists/edit.html",
        {
            "custom_list": None,
            "groups": groups,
            "all_users": users,
            "sort_orders": [s.value for s in SortOrder],
            "ops": [o.value for o in CombinationOp],
            "include_ids": [],
            "subtract_ids": [],
            "excluded_user_ids": [],
        },
    )


def _slug_valid(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


async def _save_sources(
    session: AsyncSession,
    custom_list: CustomList,
    include_ids: list[int],
    subtract_ids: list[int],
) -> None:
    # wipe existing
    await session.execute(
        delete(CustomListSource).where(CustomListSource.custom_list_id == custom_list.id)
    )
    for lid in include_ids:
        session.add(
            CustomListSource(custom_list_id=custom_list.id, list_id=lid, role=SourceRole.INCLUDE)
        )
    for lid in subtract_ids:
        # avoid duplicate keys with includes
        if lid in include_ids:
            continue
        session.add(
            CustomListSource(custom_list_id=custom_list.id, list_id=lid, role=SourceRole.SUBTRACT)
        )


async def _save_excluded_watchers(
    session: AsyncSession,
    custom_list: CustomList,
    user_ids: list[int],
) -> None:
    await session.execute(
        delete(CustomListExcludedWatcher).where(
            CustomListExcludedWatcher.custom_list_id == custom_list.id
        )
    )
    for uid in user_ids:
        session.add(CustomListExcludedWatcher(custom_list_id=custom_list.id, user_id=uid))


async def _list_form_int_list(form_field: str, request: Request) -> list[int]:
    form = await request.form()
    return [int(str(v)) for v in form.getlist(form_field) if str(v).strip()]


@router.post("/new")
async def create(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    slug: Annotated[str, Form()],
    name: Annotated[str, Form()],
    op: Annotated[str, Form()] = "union",
    sort_order: Annotated[str, Form()] = "letterboxd",
    max_items: Annotated[str, Form()] = "",
    min_rating: Annotated[str, Form()] = "",
    max_rating: Annotated[str, Form()] = "",
    min_year: Annotated[str, Form()] = "",
    max_year: Annotated[str, Form()] = "",
    rotation_enabled: Annotated[str, Form()] = "",
    rotation_batch_size: Annotated[int, Form()] = 1,
    rotation_interval: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    if not _slug_valid(slug):
        raise HTTPException(status_code=400, detail="invalid slug (lowercase alnum and -)")
    existing = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"slug already exists: {slug}")

    include_ids = await _list_form_int_list("include_ids", request)
    subtract_ids = await _list_form_int_list("subtract_ids", request)
    excluded_user_ids = await _list_form_int_list("excluded_user_ids", request)

    if not include_ids:
        raise HTTPException(status_code=400, detail="at least one include source is required")

    cl = CustomList(
        slug=slug,
        name=name,
        op=CombinationOp(op),
        sort_order=SortOrder(sort_order),
        max_items=_parse_optional_int(max_items),
        min_rating=_parse_optional_float(min_rating),
        max_rating=_parse_optional_float(max_rating),
        min_year=_parse_optional_int(min_year),
        max_year=_parse_optional_int(max_year),
        rotation_enabled=rotation_enabled == "on",
        rotation_batch_size=rotation_batch_size,
        rotation_interval=timedelta(hours=rotation_interval) if rotation_interval > 0 else None,
    )
    session.add(cl)
    await session.flush()
    await _save_sources(session, cl, include_ids, subtract_ids)
    await _save_excluded_watchers(session, cl, excluded_user_ids)
    await session.flush()
    await init_items(session, cl)
    await session.commit()
    logger.info("custom_list.created", slug=slug, custom_list_id=cl.id)
    return RedirectResponse(url="/custom-lists", status_code=303)


@router.get("/{slug}/edit", response_class=HTMLResponse)
async def edit_form(
    request: Request,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)
    groups = await _all_sources(session)
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    include_ids = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListSource.list_id).where(
                    CustomListSource.custom_list_id == cl.id,
                    CustomListSource.role == SourceRole.INCLUDE,
                )
            )
        ).all()
    ]
    subtract_ids = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListSource.list_id).where(
                    CustomListSource.custom_list_id == cl.id,
                    CustomListSource.role == SourceRole.SUBTRACT,
                )
            )
        ).all()
    ]
    excluded_user_ids = [
        row[0]
        for row in (
            await session.execute(
                select(CustomListExcludedWatcher.user_id).where(
                    CustomListExcludedWatcher.custom_list_id == cl.id
                )
            )
        ).all()
    ]
    return templates.TemplateResponse(
        request,
        "custom_lists/edit.html",
        {
            "custom_list": cl,
            "groups": groups,
            "all_users": users,
            "sort_orders": [s.value for s in SortOrder],
            "ops": [o.value for o in CombinationOp],
            "include_ids": include_ids,
            "subtract_ids": subtract_ids,
            "excluded_user_ids": excluded_user_ids,
        },
    )


@router.post("/{slug}/edit")
async def update(
    request: Request,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str, Form()],
    op: Annotated[str, Form()] = "union",
    sort_order: Annotated[str, Form()] = "letterboxd",
    max_items: Annotated[str, Form()] = "",
    min_rating: Annotated[str, Form()] = "",
    max_rating: Annotated[str, Form()] = "",
    min_year: Annotated[str, Form()] = "",
    max_year: Annotated[str, Form()] = "",
    rotation_enabled: Annotated[str, Form()] = "",
    rotation_batch_size: Annotated[int, Form()] = 1,
    rotation_interval: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)

    include_ids = await _list_form_int_list("include_ids", request)
    subtract_ids = await _list_form_int_list("subtract_ids", request)
    excluded_user_ids = await _list_form_int_list("excluded_user_ids", request)

    if not include_ids:
        raise HTTPException(status_code=400, detail="at least one include source is required")

    cl.name = name
    cl.op = CombinationOp(op)
    cl.sort_order = SortOrder(sort_order)
    cl.max_items = _parse_optional_int(max_items)
    cl.min_rating = _parse_optional_float(min_rating)
    cl.max_rating = _parse_optional_float(max_rating)
    cl.min_year = _parse_optional_int(min_year)
    cl.max_year = _parse_optional_int(max_year)
    cl.rotation_enabled = rotation_enabled == "on"
    cl.rotation_batch_size = rotation_batch_size
    cl.rotation_interval = (
        timedelta(hours=rotation_interval) if rotation_interval > 0 else None
    )

    await _save_sources(session, cl, include_ids, subtract_ids)
    await _save_excluded_watchers(session, cl, excluded_user_ids)
    await session.flush()
    await recalculate(session, cl)
    await session.commit()
    logger.info("custom_list.updated", slug=slug, custom_list_id=cl.id)
    return RedirectResponse(url="/custom-lists", status_code=303)


@router.post("/{slug}/delete")
async def delete_custom_list(
    request: Request,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)
    await session.delete(cl)
    await session.commit()
    return RedirectResponse(url="/custom-lists", status_code=303)


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """HTMX endpoint: returns a fragment with the eligible pool count for the
    sources currently selected in the editor."""
    form = await request.form()
    include_ids = [int(str(v)) for v in form.getlist("include_ids") if str(v).strip()]
    subtract_ids = [int(str(v)) for v in form.getlist("subtract_ids") if str(v).strip()]
    excluded_user_ids = [int(str(v)) for v in form.getlist("excluded_user_ids") if str(v).strip()]
    op_value = str(form.get("op", "union"))

    if not include_ids:
        return HTMLResponse('<small id="pool-preview">Pool: select at least one include source</small>')

    # build a transient CustomList object (not persisted) to reuse the resolver
    cl = CustomList(
        slug="__preview__",
        name="preview",
        op=CombinationOp(op_value),
        sort_order=SortOrder.LETTERBOXD,
        rotation_enabled=False,
        rotation_batch_size=1,
        enabled=True,
    )

    # The resolver reads sources from the DB via custom_list_id; for preview we
    # need an alternative path. We inline a quick computation here to avoid
    # persisting a row.
    from watchlistarr.services.custom_lists import (
        _combine_includes,
        _items_by_list,
        _watched_by_users,
    )

    by_list = await _items_by_list(session, list(set(include_ids + subtract_ids)))
    includes = _combine_includes((by_list.get(lid, set()) for lid in include_ids), cl.op)
    subtracts: set[int] = set()
    for lid in subtract_ids:
        subtracts |= by_list.get(lid, set())
    watched = await _watched_by_users(session, excluded_user_ids)
    universe = includes - subtracts - watched
    return HTMLResponse(
        f'<small id="pool-preview">Pool: <strong>{len(universe)}</strong> films eligible</small>'
    )
