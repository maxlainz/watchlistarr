from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base
from watchlistarr.models.enums import SourceRole
from watchlistarr.models.lists import List

if TYPE_CHECKING:
    from watchlistarr.models.custom_lists import CustomList


class CustomListSource(Base):
    __tablename__ = "custom_list_sources"
    __table_args__ = (
        Index("ix_custom_list_sources_list_id", "list_id"),
        Index("ix_custom_list_sources_source_custom_list_id", "source_custom_list_id"),
        UniqueConstraint(
            "custom_list_id",
            "role",
            "list_id",
            name="uq_custom_list_sources_list",
        ),
        UniqueConstraint(
            "custom_list_id",
            "role",
            "source_custom_list_id",
            name="uq_custom_list_sources_custom_list",
        ),
        CheckConstraint(
            "(list_id IS NOT NULL AND source_custom_list_id IS NULL) OR "
            "(list_id IS NULL AND source_custom_list_id IS NOT NULL)",
            name="ck_custom_list_sources_target_exactly_one",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    custom_list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_lists.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[SourceRole] = mapped_column(
        SAEnum(
            SourceRole,
            name="source_role_enum",
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
    list_id: Mapped[int | None] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), nullable=True
    )
    source_custom_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("custom_lists.id", ondelete="CASCADE"), nullable=True
    )

    custom_list: Mapped[CustomList] = relationship(
        back_populates="sources", foreign_keys=[custom_list_id]
    )
    list: Mapped[List | None] = relationship(foreign_keys=[list_id])
    source_custom_list: Mapped[CustomList | None] = relationship(
        foreign_keys=[source_custom_list_id]
    )
