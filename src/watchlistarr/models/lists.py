from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Interval, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base
from watchlistarr.models.enums import SourceType, SyncStatus

if TYPE_CHECKING:
    from watchlistarr.models.list_items import ListItem
    from watchlistarr.models.users import User


class List(Base):
    __tablename__ = "lists"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_lists_user_slug"),
        UniqueConstraint("letterboxd_list_id", name="uq_lists_letterboxd_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(
            SourceType,
            name="source_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
    letterboxd_list_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    film_count: Mapped[int] = mapped_column(default=0)
    enabled: Mapped[bool] = mapped_column(default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_sync_status: Mapped[SyncStatus] = mapped_column(
        SAEnum(
            SyncStatus,
            name="sync_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=SyncStatus.NEVER,
    )

    lists_incremental_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    lists_full_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    min_sync_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    flap_confirm_scrapes: Mapped[int | None] = mapped_column(nullable=True)

    user: Mapped[User] = relationship(back_populates="lists")
    items: Mapped[list[ListItem]] = relationship(
        back_populates="list", cascade="all, delete-orphan"
    )
