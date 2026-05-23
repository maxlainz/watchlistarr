import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.config import get_settings
from watchlistarr.db import get_session, get_session_factory
from watchlistarr.models.base import utcnow
from watchlistarr.models.custom_list_excluded_watchers import CustomListExcludedWatcher
from watchlistarr.models.custom_list_items import CustomListItem
from watchlistarr.models.custom_list_sources import CustomListSource
from watchlistarr.models.custom_lists import CustomList
from watchlistarr.models.enums import (
    CombinationOp,
    ScrapeSource,
    ScrapeStatus,
    SortOrder,
    SourceRole,
    SourceType,
    SyncStatus,
)
from watchlistarr.models.list_items import ListItem
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.scrape_runs import ScrapeRun
from watchlistarr.models.users import User
from watchlistarr.services.custom_lists import (
    _combine_includes,
    _items_by_list,
    _watched_by_users,
    describe_sources,
    init_items,
    recalculate,
)
from watchlistarr.services.letterboxd.client import LetterboxdClient
from watchlistarr.services.log_buffer import get_buffer
from watchlistarr.services.onboarding import schedule_initial_run, schedule_list_sync
from watchlistarr.services.scrape.initial_run import UserValidationError, validate_username

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ───────────────────────── helpers ─────────────────────────


def _td_hours(td: timedelta | None) -> int | None:
    if td is None:
        return None
    return int(td.total_seconds() // 3600)


def _td_from_hours(hours: int | None) -> timedelta | None:
    if hours is None or hours <= 0:
        return None
    return timedelta(hours=hours)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def _sync_status_to_design(status: SyncStatus) -> str | None:
    if status is SyncStatus.SUCCESS:
        return "success"
    if status is SyncStatus.ERROR:
        return "error"
    return None


def _items_count(session: AsyncSession, list_id: int) -> Any:
    return session.execute(select(func.count(ListItem.list_id)).where(ListItem.list_id == list_id))


async def _running_scrapes(session: AsyncSession) -> tuple[set[int], set[int]]:
    """Snapshot of in-flight scrapes. Returns (discovery_user_ids, syncing_list_ids).

    Powers the UI's spinner — `_serialize_user` consults this to mark a user as
    `discoveryRunning` and to flag individual lists in `syncingListIds`."""
    rows = (
        await session.execute(
            select(ScrapeRun.source, ScrapeRun.target_id).where(
                ScrapeRun.status == ScrapeStatus.RUNNING
            )
        )
    ).all()
    discovery: set[int] = set()
    list_runs: set[int] = set()
    for source, target_id in rows:
        if target_id is None:
            continue
        if source is ScrapeSource.DISCOVERY:
            discovery.add(target_id)
        elif source in (ScrapeSource.LIST, ScrapeSource.WATCHLIST):
            list_runs.add(target_id)
    return discovery, list_runs


async def _serialize_user(
    session: AsyncSession,
    user: User,
    *,
    include_lists: bool = True,
    running: tuple[set[int], set[int]] | None = None,
) -> dict[str, Any]:
    if running is None:
        running = await _running_scrapes(session)
    discovery_users, syncing_list_ids = running

    lists = list(
        (await session.execute(select(ListModel).where(ListModel.user_id == user.id)))
        .scalars()
        .all()
    )
    enabled_count = sum(1 for lst in lists if lst.enabled)
    serialized_lists: list[dict[str, Any]] = []
    if include_lists:
        # Stable order: watchlist first, then alpha by name.
        lists.sort(
            key=lambda lst: (
                0 if lst.source_type is SourceType.WATCHLIST else 1,
                lst.name.lower(),
            )
        )
        env = get_settings()
        for lst in lists:
            count = (await _items_count(session, lst.id)).scalar_one()
            is_wl = lst.source_type is SourceType.WATCHLIST
            advanced = {
                "incrementalInterval": _td_hours(
                    user.watchlist_incremental_interval if is_wl else lst.lists_incremental_interval
                ),
                "fullInterval": _td_hours(
                    user.watchlist_full_interval if is_wl else lst.lists_full_interval
                ),
                "flapConfirmScrapes": lst.flap_confirm_scrapes,
                "defaultIncrementalInterval": _td_hours(
                    env.watchlist_incremental_interval if is_wl else env.lists_incremental_interval
                ),
                "defaultFullInterval": _td_hours(
                    env.watchlist_full_interval if is_wl else env.lists_full_interval
                ),
                "defaultFlapConfirmScrapes": env.flap_confirm_scrapes,
            }
            serialized_lists.append(
                {
                    "id": lst.id,
                    "slug": lst.slug,
                    "name": "Watchlist" if is_wl else lst.name,
                    "sourceType": lst.source_type.value,
                    "enabled": lst.enabled,
                    "filmCount": count,
                    "lastSyncedAt": _iso(lst.last_synced_at),
                    "status": _sync_status_to_design(lst.last_sync_status),
                    "advanced": advanced,
                }
            )
    return {
        "id": user.id,
        "username": user.letterboxd_username,
        "displayName": user.display_name or user.letterboxd_username,
        "addedAt": _iso(user.added_at),
        "enabledCount": enabled_count,
        "totalLists": len(lists),
        "lists": serialized_lists,
        "discoveryRunning": user.id in discovery_users,
        "syncingListIds": [lst.id for lst in lists if lst.id in syncing_list_ids],
    }


async def _serialize_custom_list(session: AsyncSession, cl: CustomList) -> dict[str, Any]:
    sources_rows = list(
        (
            await session.execute(
                select(CustomListSource).where(CustomListSource.custom_list_id == cl.id)
            )
        )
        .scalars()
        .all()
    )
    list_ids = [s.list_id for s in sources_rows]
    lists_by_id: dict[int, tuple[ListModel, User]] = {}
    if list_ids:
        rows = (
            await session.execute(
                select(ListModel, User)
                .join(User, User.id == ListModel.user_id)
                .where(ListModel.id.in_(list_ids))
            )
        ).all()
        for lst, usr in rows:
            lists_by_id[lst.id] = (lst, usr)

    sources_payload: list[dict[str, Any]] = []
    for src in sources_rows:
        entry = lists_by_id.get(src.list_id)
        if entry is None:
            continue
        lst, usr = entry
        sources_payload.append(
            {
                "listId": lst.id,
                "name": "Watchlist" if lst.source_type is SourceType.WATCHLIST else lst.name,
                "username": usr.letterboxd_username,
                "role": src.role.value,
            }
        )

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
    excluded_usernames: list[str] = []
    if excluded_user_ids:
        username_rows = (
            await session.execute(
                select(User.letterboxd_username).where(User.id.in_(excluded_user_ids))
            )
        ).all()
        excluded_usernames = [r[0] for r in username_rows]

    items_count = (
        await session.execute(
            select(func.count(CustomListItem.custom_list_id)).where(
                CustomListItem.custom_list_id == cl.id
            )
        )
    ).scalar_one()
    summary = await describe_sources(session, cl)

    return {
        "id": cl.id,
        "slug": cl.slug,
        "name": cl.name,
        "op": cl.op.value,
        "sources": sources_payload,
        "excludedWatchers": excluded_usernames,
        "excludedUserIds": excluded_user_ids,
        "itemsServed": items_count,
        "maxItems": cl.max_items,
        "sortOrder": cl.sort_order.value,
        "minRating": cl.min_rating,
        "maxRating": cl.max_rating,
        "minYear": cl.min_year,
        "maxYear": cl.max_year,
        "yearLastN": cl.year_last_n,
        "addedLastNDays": cl.added_last_n_days,
        "rotationEnabled": cl.rotation_enabled,
        "rotationInterval": _td_hours(cl.rotation_interval),
        "rotationBatchSize": cl.rotation_batch_size,
        "snapshotInterval": _td_hours(cl.snapshot_interval),
        "lastSnapshotAt": _iso(cl.last_snapshot_at),
        "enabled": cl.enabled,
        "summary": summary,
    }


async def _all_users(session: AsyncSession) -> list[dict[str, Any]]:
    running = await _running_scrapes(session)
    users = list((await session.execute(select(User).order_by(User.id))).scalars().all())
    return [await _serialize_user(session, u, running=running) for u in users]


async def _all_custom_lists(session: AsyncSession) -> list[dict[str, Any]]:
    cls = list(
        (await session.execute(select(CustomList).order_by(CustomList.name))).scalars().all()
    )
    return [await _serialize_custom_list(session, cl) for cl in cls]


def _job_label(job_id: str, users_by_id: dict[int, str]) -> dict[str, str]:
    """Pretty-print an APScheduler job id for the dashboard 'next scheduled' panel."""
    if job_id == "rotation-tick":
        return {"label": "Custom lists", "detail": "Rotation tick", "kind": "rotation"}
    parts = job_id.split("-")
    if len(parts) >= 2 and parts[0] == "rss":
        uid = int(parts[-1])
        return {
            "label": f"{users_by_id.get(uid, '?')} RSS",
            "detail": "Viewing logs poll",
            "kind": "watched",
        }
    if len(parts) >= 2 and parts[0] == "discovery":
        uid = int(parts[-1])
        return {
            "label": f"{users_by_id.get(uid, '?')} discovery",
            "detail": "Refresh public lists",
            "kind": "sync",
        }
    if job_id.startswith("films-backstop-"):
        uid = int(job_id.rsplit("-", 1)[-1])
        return {
            "label": f"{users_by_id.get(uid, '?')} films",
            "detail": "Backstop /films/ page",
            "kind": "watched",
        }
    if job_id.startswith("watchlist-incr-") or job_id.startswith("watchlist-full-"):
        uid = int(job_id.rsplit("-", 1)[-1])
        kind = "Incremental" if "incr" in job_id else "Full"
        return {
            "label": f"{users_by_id.get(uid, '?')}/watchlist",
            "detail": f"{kind} scrape",
            "kind": "sync",
        }
    if job_id.startswith("list-incr-") or job_id.startswith("list-full-"):
        kind = "Incremental" if "incr" in job_id else "Full"
        return {
            "label": f"list #{job_id.rsplit('-', 1)[-1]}",
            "detail": f"{kind} scrape",
            "kind": "sync",
        }
    return {"label": job_id, "detail": "Scheduled job", "kind": "sync"}


def _humanize_eta(dt: datetime) -> str:
    delta = dt - datetime.now(tz=dt.tzinfo or UTC)
    total = int(delta.total_seconds())
    if total <= 0:
        return "now"
    if total < 60:
        return f"in {total}s"
    if total < 3600:
        return f"in {total // 60} min"
    hours, mins = divmod(total // 60, 60)
    return f"in {hours}h {mins:02d}m"


async def _dashboard_payload(session: AsyncSession, scheduler: object | None) -> dict[str, Any]:
    users_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    lists_count = (
        await session.execute(select(func.count(ListModel.id)).where(ListModel.enabled.is_(True)))
    ).scalar_one()
    custom_count = (
        await session.execute(select(func.count(CustomList.id)).where(CustomList.enabled.is_(True)))
    ).scalar_one()
    items_served = (
        await session.execute(select(func.count(CustomListItem.custom_list_id)))
    ).scalar_one()

    one_hour_ago = utcnow() - timedelta(hours=1)
    recent_errors = (
        await session.execute(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == ScrapeStatus.ERROR,
                ScrapeRun.started_at >= one_hour_ago,
            )
        )
    ).scalar_one()

    runs = list(
        (await session.execute(select(ScrapeRun).order_by(desc(ScrapeRun.started_at)).limit(12)))
        .scalars()
        .all()
    )
    users_by_id = {
        u.id: u.letterboxd_username for u in (await session.execute(select(User))).scalars().all()
    }
    lists_by_id = {
        lst.id: lst for lst in (await session.execute(select(ListModel))).scalars().all()
    }
    recent_activity = []
    for run in runs:
        kind = "sync"
        if run.status is ScrapeStatus.ERROR:
            kind = "error"
        elif run.source is ScrapeSource.RSS:
            kind = "watched"
        elif run.source is ScrapeSource.ROTATION:
            kind = "rotation"
        status = (
            "error"
            if run.status is ScrapeStatus.ERROR
            else "info"
            if kind == "watched"
            else "success"
        )
        target_label: str
        if run.source in (ScrapeSource.LIST, ScrapeSource.WATCHLIST) and run.target_id is not None:
            lst = lists_by_id.get(run.target_id)
            if lst is not None:
                uname = users_by_id.get(lst.user_id, "?")
                target_label = f"{uname}/{lst.slug}"
            else:
                target_label = f"list #{run.target_id}"
        elif run.target_id is not None and run.target_id in users_by_id:
            target_label = users_by_id[run.target_id]
        else:
            target_label = run.source.value
        text = f"{target_label} — {run.source.value}"
        if run.error:
            text = f"{target_label} failed: {run.error[:80]}"
        recent_activity.append(
            {
                "ts": _iso(run.started_at),
                "kind": kind,
                "text": text,
                "status": status,
            }
        )

    upcoming: list[dict[str, Any]] = []
    if scheduler is not None and hasattr(scheduler, "upcoming_jobs"):
        for job in scheduler.upcoming_jobs(limit=5):
            label = _job_label(job["id"], users_by_id)
            upcoming.append(
                {
                    **label,
                    "eta": _humanize_eta(job["next_run_time"]),
                    "nextRunAt": _iso(job["next_run_time"]),
                }
            )

    return {
        "stats": {
            "usersCount": users_count,
            "listsCount": lists_count,
            "customCount": custom_count,
            "itemsServed": items_served,
            "recentErrors": recent_errors,
        },
        "recentActivity": recent_activity,
        "upcoming": upcoming,
    }


# ───────────────────────── endpoints ─────────────────────────


@router.get("/bootstrap")
async def bootstrap(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    scheduler = getattr(request.app.state, "scheduler", None)
    return JSONResponse(
        {
            "users": await _all_users(session),
            "customLists": await _all_custom_lists(session),
            "dashboard": await _dashboard_payload(session, scheduler),
        }
    )


@router.get("/users")
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    return JSONResponse(await _all_users(session))


@router.post("/users")
async def add_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    username = str(payload.get("username", "")).strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="username is required")
    settings = get_settings()
    client = LetterboxdClient(settings)
    try:
        try:
            validated = await validate_username(client, username)
        except UserValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await client.aclose()

    existing = (
        await session.execute(select(User).where(User.letterboxd_username == validated))
    ).scalar_one_or_none()
    if existing is not None:
        return JSONResponse(await _serialize_user(session, existing), status_code=200)

    user = User(letterboxd_username=validated)
    session.add(user)
    await session.flush()
    await session.commit()

    scheduler = getattr(request.app.state, "scheduler", None)
    schedule_initial_run(get_session_factory(), settings, user.id, scheduler)
    logger.info("user.added", username=validated, user_id=user.id)
    return JSONResponse(await _serialize_user(session, user), status_code=201)


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    await session.delete(user)
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return JSONResponse({"ok": True})


@router.post("/users/{username}/lists/{list_id}/toggle")
async def toggle_list(
    username: str,
    list_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    lst = await session.get(ListModel, list_id)
    if lst is None or lst.user_id != user.id:
        raise HTTPException(status_code=404)
    was_enabled = lst.enabled
    lst.enabled = not was_enabled
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    # Off → On: kick an immediate full sync so the user does not wait for the
    # next scheduler tick. Skip if an audit run is already in flight for this
    # list (the onboarding background job, or a previous toggle).
    if lst.enabled and not was_enabled:
        in_flight = (
            await session.execute(
                select(ScrapeRun.id)
                .where(
                    ScrapeRun.target_id == lst.id,
                    ScrapeRun.source.in_((ScrapeSource.LIST, ScrapeSource.WATCHLIST)),
                    ScrapeRun.status == ScrapeStatus.RUNNING,
                )
                .limit(1)
            )
        ).first()
        if in_flight is None:
            schedule_list_sync(get_session_factory(), get_settings(), lst.id)
    return JSONResponse(await _serialize_user(session, user))


@router.post("/users/{username}/lists/{list_id}/settings")
async def save_list_settings(
    username: str,
    list_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    user = (
        await session.execute(select(User).where(User.letterboxd_username == username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404)
    lst = await session.get(ListModel, list_id)
    if lst is None or lst.user_id != user.id:
        raise HTTPException(status_code=404)

    inc = _parse_optional_int(payload.get("incrementalInterval"))
    full = _parse_optional_int(payload.get("fullInterval"))
    flap = _parse_optional_int(payload.get("flapConfirmScrapes"))

    if lst.source_type is SourceType.WATCHLIST:
        user.watchlist_incremental_interval = _td_from_hours(inc)
        user.watchlist_full_interval = _td_from_hours(full)
    else:
        lst.lists_incremental_interval = _td_from_hours(inc)
        lst.lists_full_interval = _td_from_hours(full)
    lst.flap_confirm_scrapes = flap
    await session.commit()
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await scheduler.sync_jobs()
    return JSONResponse(await _serialize_user(session, user))


@router.get("/custom-lists")
async def custom_lists_index(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    return JSONResponse(await _all_custom_lists(session))


@router.get("/custom-lists/{slug}")
async def custom_list_detail(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)
    return JSONResponse(await _serialize_custom_list(session, cl))


def _parse_optional_int(value: Any) -> int | None:
    """Devuelve ``None`` para ``None``, ``""`` y **también ``0``**.

    La UI envía ``0`` cuando el usuario vacía un campo numérico (maxItems,
    rotationInterval, yearLastN, etc.). El backend lo interpreta como
    "sin valor". Consecuencia: no se puede setear ``maxItems=0`` legítimamente
    vía API — usar ``None`` para "sin tope". Difiere de
    ``_parse_optional_float`` que sí distingue ``0.0`` de ``None`` (necesario
    para ``minRating=0``).
    """
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_float(value: Any) -> float | None:
    """Devuelve ``None`` para ``None`` y ``""``. ``0.0`` se preserva como
    valor real (necesario para ``minRating=0`` en filtros de custom list).
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _save_sources(
    session: AsyncSession,
    custom_list: CustomList,
    include_ids: list[int],
    subtract_ids: list[int],
) -> None:
    await session.execute(
        delete(CustomListSource).where(CustomListSource.custom_list_id == custom_list.id)
    )
    for lid in include_ids:
        session.add(
            CustomListSource(custom_list_id=custom_list.id, list_id=lid, role=SourceRole.INCLUDE)
        )
    for lid in subtract_ids:
        if lid in include_ids:
            continue
        session.add(
            CustomListSource(custom_list_id=custom_list.id, list_id=lid, role=SourceRole.SUBTRACT)
        )


async def _save_excluded(
    session: AsyncSession, custom_list: CustomList, user_ids: list[int]
) -> None:
    await session.execute(
        delete(CustomListExcludedWatcher).where(
            CustomListExcludedWatcher.custom_list_id == custom_list.id
        )
    )
    for uid in user_ids:
        session.add(CustomListExcludedWatcher(custom_list_id=custom_list.id, user_id=uid))


def _split_sources(payload: dict[str, Any]) -> tuple[list[int], list[int]]:
    sources = payload.get("sources", []) or []
    include_ids: list[int] = []
    subtract_ids: list[int] = []
    for src in sources:
        role = src.get("role", "include")
        try:
            lid = int(src["listId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid source") from exc
        if role == SourceRole.SUBTRACT.value:
            subtract_ids.append(lid)
        else:
            include_ids.append(lid)
    return include_ids, subtract_ids


async def _resolve_excluded_user_ids(session: AsyncSession, payload: dict[str, Any]) -> list[int]:
    if "excludedUserIds" in payload:
        return [int(x) for x in payload["excludedUserIds"]]
    usernames = payload.get("excludedWatchers", []) or []
    if not usernames:
        return []
    rows = (
        await session.execute(select(User.id).where(User.letterboxd_username.in_(usernames)))
    ).all()
    return [r[0] for r in rows]


@router.post("/custom-lists")
async def create_custom_list(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    slug = str(payload.get("slug", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="invalid slug (lowercase alnum and -)")

    existing = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"slug already exists: {slug}")

    include_ids, subtract_ids = _split_sources(payload)
    if not include_ids:
        raise HTTPException(status_code=400, detail="at least one include source is required")
    excluded_user_ids = await _resolve_excluded_user_ids(session, payload)

    year_last_n = _parse_optional_int(payload.get("yearLastN"))
    if year_last_n is not None:
        min_year = None
        max_year = None
    else:
        min_year = _parse_optional_int(payload.get("minYear"))
        max_year = _parse_optional_int(payload.get("maxYear"))
    added_last_n_days = _parse_optional_int(payload.get("addedLastNDays"))

    cl = CustomList(
        slug=slug,
        name=name,
        op=CombinationOp(payload.get("op", "union")),
        sort_order=SortOrder(payload.get("sortOrder", "letterboxd")),
        max_items=_parse_optional_int(payload.get("maxItems")),
        min_rating=_parse_optional_float(payload.get("minRating")),
        max_rating=_parse_optional_float(payload.get("maxRating")),
        min_year=min_year,
        max_year=max_year,
        year_last_n=year_last_n,
        added_last_n_days=added_last_n_days,
        rotation_enabled=bool(payload.get("rotationEnabled")),
        rotation_batch_size=int(payload.get("rotationBatchSize") or 1),
        rotation_interval=_td_from_hours(payload.get("rotationInterval")),
        snapshot_interval=_td_from_hours(payload.get("snapshotInterval")),
    )
    session.add(cl)
    await session.flush()
    await _save_sources(session, cl, include_ids, subtract_ids)
    await _save_excluded(session, cl, excluded_user_ids)
    await session.flush()
    await init_items(session, cl)
    await session.commit()
    logger.info("custom_list.created", slug=slug, custom_list_id=cl.id)
    return JSONResponse(await _serialize_custom_list(session, cl), status_code=201)


@router.put("/custom-lists/{slug}")
async def update_custom_list(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)

    include_ids, subtract_ids = _split_sources(payload)
    if not include_ids:
        raise HTTPException(status_code=400, detail="at least one include source is required")
    excluded_user_ids = await _resolve_excluded_user_ids(session, payload)

    cl.name = str(payload.get("name", cl.name)).strip()
    cl.op = CombinationOp(payload.get("op", cl.op.value))
    cl.sort_order = SortOrder(payload.get("sortOrder", cl.sort_order.value))
    cl.max_items = _parse_optional_int(payload.get("maxItems"))
    cl.min_rating = _parse_optional_float(payload.get("minRating"))
    cl.max_rating = _parse_optional_float(payload.get("maxRating"))
    year_last_n = _parse_optional_int(payload.get("yearLastN"))
    if year_last_n is not None:
        cl.year_last_n = year_last_n
        cl.min_year = None
        cl.max_year = None
    else:
        cl.year_last_n = None
        cl.min_year = _parse_optional_int(payload.get("minYear"))
        cl.max_year = _parse_optional_int(payload.get("maxYear"))
    cl.added_last_n_days = _parse_optional_int(payload.get("addedLastNDays"))
    cl.rotation_enabled = bool(payload.get("rotationEnabled"))
    cl.rotation_batch_size = int(payload.get("rotationBatchSize") or 1)
    cl.rotation_interval = _td_from_hours(payload.get("rotationInterval"))
    cl.snapshot_interval = _td_from_hours(payload.get("snapshotInterval"))

    await _save_sources(session, cl, include_ids, subtract_ids)
    await _save_excluded(session, cl, excluded_user_ids)
    await session.flush()
    await recalculate(session, cl)
    await session.commit()
    logger.info("custom_list.updated", slug=slug, custom_list_id=cl.id)
    return JSONResponse(await _serialize_custom_list(session, cl))


@router.delete("/custom-lists/{slug}")
async def delete_custom_list(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    cl = (
        await session.execute(select(CustomList).where(CustomList.slug == slug))
    ).scalar_one_or_none()
    if cl is None:
        raise HTTPException(status_code=404)
    await session.delete(cl)
    await session.commit()
    return JSONResponse({"ok": True})


@router.post("/custom-lists/preview")
async def preview_custom_list(
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    include_ids, subtract_ids = _split_sources(payload)
    if not include_ids:
        return JSONResponse({"pool": 0})
    op_value = payload.get("op", "union")
    excluded_user_ids = await _resolve_excluded_user_ids(session, payload)

    by_list = await _items_by_list(session, list(set(include_ids + subtract_ids)))
    includes = _combine_includes(
        (by_list.get(lid, set()) for lid in include_ids), CombinationOp(op_value)
    )
    subtracts: set[int] = set()
    for lid in subtract_ids:
        subtracts |= by_list.get(lid, set())
    watched = await _watched_by_users(session, excluded_user_ids)
    universe = includes - subtracts - watched
    return JSONResponse({"pool": len(universe)})


@router.get("/activity")
async def activity_tail(
    since: Annotated[int, Query(ge=0)] = 0,
    level: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    buf = get_buffer()
    lines = buf.snapshot(since=since)
    if level:
        wanted = level.upper()
        lines = [line for line in lines if line.level == wanted]
    payload = [
        {
            "seq": line.seq,
            "ts": _iso(line.ts),
            "level": line.level,
            "src": line.src,
            "message": line.message,
            "event": line.event,
            "fields": line.fields,
            "humanMessage": line.human_message or line.message,
            "excInfo": line.exc_info,
        }
        for line in lines
    ]
    return JSONResponse({"lines": payload, "latestSeq": buf.latest_seq()})


@router.get("/activity/download")
async def activity_download() -> PlainTextResponse:
    return PlainTextResponse(
        get_buffer().dump_text(),
        headers={"Content-Disposition": "attachment; filename=watchlistarr.log"},
    )


@router.get("/dashboard")
async def dashboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    scheduler = getattr(request.app.state, "scheduler", None)
    return JSONResponse(await _dashboard_payload(session, scheduler))
