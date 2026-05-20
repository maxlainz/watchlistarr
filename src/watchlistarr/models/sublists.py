from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Interval, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base
from watchlistarr.models.enums import CombinedKind, SortOrder

if TYPE_CHECKING:
    from watchlistarr.models.sublist_items import SublistItem
    from watchlistarr.models.users import User


class Sublist(Base):
    __tablename__ = "sublists"
    __table_args__ = (
        CheckConstraint(
            "(parent_list_id IS NOT NULL AND parent_combined_kind IS NULL) "
            "OR (parent_list_id IS NULL AND parent_combined_kind IS NOT NULL)",
            name="ck_sublists_parent_exclusive",
        ),
        Index(
            "uq_sublists_user_slug",
            "user_id",
            "slug",
            unique=True,
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_sublists_combined_slug",
            "parent_combined_kind",
            "slug",
            unique=True,
            sqlite_where=text("parent_combined_kind IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_combined_kind: Mapped[CombinedKind | None] = mapped_column(
        SAEnum(
            CombinedKind,
            name="combined_kind_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )
    slug: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    max_items: Mapped[int | None] = mapped_column(nullable=True)
    sort_order: Mapped[SortOrder] = mapped_column(
        SAEnum(
            SortOrder,
            name="sort_order_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=SortOrder.LETTERBOXD,
    )
    min_rating: Mapped[float | None] = mapped_column(nullable=True)
    max_rating: Mapped[float | None] = mapped_column(nullable=True)
    min_year: Mapped[int | None] = mapped_column(nullable=True)
    max_year: Mapped[int | None] = mapped_column(nullable=True)
    added_after: Mapped[datetime | None] = mapped_column(nullable=True)
    added_before: Mapped[datetime | None] = mapped_column(nullable=True)
    rotation_enabled: Mapped[bool] = mapped_column(default=False)
    rotation_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    rotation_batch_size: Mapped[int] = mapped_column(default=1)
    last_rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)

    user: Mapped[User | None] = relationship(back_populates="sublists")
    items: Mapped[list[SublistItem]] = relationship(
        back_populates="sublist", cascade="all, delete-orphan"
    )
