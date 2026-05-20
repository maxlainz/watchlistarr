from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base
from watchlistarr.models.enums import SourceRole
from watchlistarr.models.lists import List

if TYPE_CHECKING:
    from watchlistarr.models.custom_lists import CustomList


class CustomListSource(Base):
    __tablename__ = "custom_list_sources"
    __table_args__ = (Index("ix_custom_list_sources_list_id", "list_id"),)

    custom_list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_lists.id", ondelete="CASCADE"), primary_key=True
    )
    list_id: Mapped[int] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[SourceRole] = mapped_column(
        SAEnum(
            SourceRole,
            name="source_role_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        primary_key=True,
    )

    custom_list: Mapped[CustomList] = relationship(back_populates="sources")
    list: Mapped[List] = relationship()
