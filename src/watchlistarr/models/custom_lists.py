from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Interval, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base
from watchlistarr.models.enums import CombinationOp, SortOrder

if TYPE_CHECKING:
    from watchlistarr.models.custom_list_excluded_watchers import CustomListExcludedWatcher
    from watchlistarr.models.custom_list_items import CustomListItem
    from watchlistarr.models.custom_list_sources import CustomListSource


class CustomList(Base):
    __tablename__ = "custom_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    op: Mapped[CombinationOp] = mapped_column(
        SAEnum(
            CombinationOp,
            name="combination_op_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=CombinationOp.UNION,
    )
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
    year_last_n: Mapped[int | None] = mapped_column(nullable=True)
    added_after: Mapped[datetime | None] = mapped_column(nullable=True)
    added_before: Mapped[datetime | None] = mapped_column(nullable=True)
    added_last_n_days: Mapped[int | None] = mapped_column(nullable=True)
    rotation_enabled: Mapped[bool] = mapped_column(default=False)
    rotation_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    rotation_batch_size: Mapped[int] = mapped_column(default=1)
    last_rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    snapshot_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    last_snapshot_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)

    items: Mapped[list[CustomListItem]] = relationship(
        back_populates="custom_list", cascade="all, delete-orphan"
    )
    sources: Mapped[list[CustomListSource]] = relationship(
        back_populates="custom_list",
        cascade="all, delete-orphan",
        foreign_keys="CustomListSource.custom_list_id",
    )
    excluded_watchers: Mapped[list[CustomListExcludedWatcher]] = relationship(
        back_populates="custom_list", cascade="all, delete-orphan"
    )
