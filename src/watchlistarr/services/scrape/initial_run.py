from __future__ import annotations

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchlistarr.models.enums import SourceType, SyncStatus
from watchlistarr.models.lists import List as ListModel
from watchlistarr.models.users import User
from watchlistarr.services.letterboxd.client import LetterboxdClient

logger = structlog.get_logger(__name__)

RESERVED_USERNAMES: frozenset[str] = frozenset(
    {"all", "api", "admin", "static", "health", "_", "lists"}
)


class UserValidationError(Exception):
    pass


async def validate_username(client: LetterboxdClient, username: str) -> str:
    if username.lower() in RESERVED_USERNAMES:
        raise UserValidationError(f"username reservado: {username}")
    if not username or "/" in username or " " in username:
        raise UserValidationError(f"username inválido: {username}")
    try:
        response = await client.get(f"/{username}/")
    except httpx.HTTPStatusError as exc:
        raise UserValidationError(
            f"username {username!r} no existe o no es accesible: {exc.response.status_code}"
        ) from exc
    letterboxd_type = response.headers.get("x-letterboxd-type", "")
    if letterboxd_type != "Member":
        raise UserValidationError(
            f"{username!r}: cabecera x-letterboxd-type={letterboxd_type!r} (esperado Member)"
        )
    return username


async def ensure_watchlist_row(session: AsyncSession, user: User) -> ListModel:
    existing = (
        await session.execute(
            select(ListModel).where(
                ListModel.user_id == user.id,
                ListModel.source_type == SourceType.WATCHLIST,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = ListModel(
        user_id=user.id,
        source_type=SourceType.WATCHLIST,
        slug="watchlist",
        name="Watchlist",
        enabled=False,
        last_sync_status=SyncStatus.NEVER,
    )
    session.add(row)
    await session.flush()
    return row
