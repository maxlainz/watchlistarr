from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.db import get_session
from watchlistarr.models.enums import CombinedKind, SortOrder, SourceType
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.sublists import Sublist
from watchlistarr.models.users import User
from watchlistarr.routes.ui import templates
from watchlistarr.services.rotation import init_sublist_items, recalculate_sublist

router = APIRouter()

_USER_RESERVED_SLUGS: frozenset[str] = frozenset({"watchlist"})
_ALL_RESERVED_SLUGS: frozenset[str] = frozenset({"watchlist"})


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


@router.get("/users/{username}/sublists/new", response_class=HTMLResponse)
async def new_user_sublist(
    request: Request,
    username: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    parents = list(
        (
            await session.execute(
                select(ListModel).where(ListModel.user_id == user.id, ListModel.enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request,
        "sublists/edit.html",
        {
            "user": user,
            "parents": parents,
            "sublist": None,
            "sort_orders": [s.value for s in SortOrder],
            "is_combined": False,
        },
    )


@router.post("/users/{username}/sublists/new")
async def create_user_sublist(
    request: Request,
    username: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    parent_list_id: Annotated[int, Form()],
    slug: Annotated[str, Form()],
    name: Annotated[str, Form()],
    sort_order: Annotated[str, Form()] = "letterboxd",
    max_items: Annotated[str, Form()] = "",
    min_rating: Annotated[str, Form()] = "",
    max_rating: Annotated[str, Form()] = "",
    min_year: Annotated[str, Form()] = "",
    max_year: Annotated[str, Form()] = "",
    rotation_enabled: Annotated[str, Form()] = "",
    rotation_batch_size: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    if slug in _USER_RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail=f"slug reservado: {slug}")
    parent = await session.get(ListModel, parent_list_id)
    if parent is None or parent.user_id != user.id:
        raise HTTPException(status_code=400, detail="parent inválido")
    existing_slugs = {
        row[0]
        for row in (
            await session.execute(select(ListModel.slug).where(ListModel.user_id == user.id))
        ).all()
    } | {
        row[0]
        for row in (
            await session.execute(select(Sublist.slug).where(Sublist.user_id == user.id))
        ).all()
    }
    if slug in existing_slugs:
        raise HTTPException(status_code=400, detail=f"slug ya existe: {slug}")

    sub = Sublist(
        user_id=user.id,
        parent_list_id=parent.id,
        slug=slug,
        name=name,
        sort_order=SortOrder(sort_order),
        max_items=_parse_optional_int(max_items),
        min_rating=_parse_optional_float(min_rating),
        max_rating=_parse_optional_float(max_rating),
        min_year=_parse_optional_int(min_year),
        max_year=_parse_optional_int(max_year),
        rotation_enabled=rotation_enabled == "on",
        rotation_batch_size=rotation_batch_size,
    )
    session.add(sub)
    await session.flush()
    await init_sublist_items(session, sub)
    await session.commit()
    return RedirectResponse(url=f"/users/{username}", status_code=303)


@router.post("/users/{username}/sublists/{slug}/delete")
async def delete_user_sublist(
    request: Request,
    username: str,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    sub = (
        await session.execute(
            select(Sublist).where(Sublist.user_id == user.id, Sublist.slug == slug)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404)
    await session.delete(sub)
    await session.commit()
    return RedirectResponse(url=f"/users/{username}", status_code=303)


@router.get("/combined/sublists/new", response_class=HTMLResponse)
async def new_combined_sublist(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "sublists/edit.html",
        {
            "user": None,
            "parents": [],
            "sublist": None,
            "sort_orders": [s.value for s in SortOrder],
            "is_combined": True,
            "combined_kinds": [k.value for k in CombinedKind],
        },
    )


@router.post("/combined/sublists/new")
async def create_combined_sublist(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    parent_combined_kind: Annotated[str, Form()],
    slug: Annotated[str, Form()],
    name: Annotated[str, Form()],
    sort_order: Annotated[str, Form()] = "letterboxd",
    max_items: Annotated[str, Form()] = "",
    min_rating: Annotated[str, Form()] = "",
    max_rating: Annotated[str, Form()] = "",
    min_year: Annotated[str, Form()] = "",
    max_year: Annotated[str, Form()] = "",
    rotation_enabled: Annotated[str, Form()] = "",
    rotation_batch_size: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    if slug in _ALL_RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail=f"slug reservado: {slug}")
    kind = CombinedKind(parent_combined_kind)
    existing = (
        await session.execute(
            select(Sublist).where(Sublist.parent_combined_kind == kind, Sublist.slug == slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="slug ya existe")
    sub = Sublist(
        parent_combined_kind=kind,
        slug=slug,
        name=name,
        sort_order=SortOrder(sort_order),
        max_items=_parse_optional_int(max_items),
        min_rating=_parse_optional_float(min_rating),
        max_rating=_parse_optional_float(max_rating),
        min_year=_parse_optional_int(min_year),
        max_year=_parse_optional_int(max_year),
        rotation_enabled=rotation_enabled == "on",
        rotation_batch_size=rotation_batch_size,
    )
    session.add(sub)
    await session.flush()
    await init_sublist_items(session, sub)
    await session.commit()
    return RedirectResponse(url="/combined", status_code=303)


_ = (SourceType, recalculate_sublist)  # mantener imports usados en futuras extensiones
