from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base, utcnow

if TYPE_CHECKING:
    from watchlistarr.models.custom_lists import CustomList
    from watchlistarr.models.films import Film


class CustomListItem(Base):
    __tablename__ = "custom_list_items"
    __table_args__ = (Index("ix_custom_list_items_served_since", "custom_list_id", "served_since"),)

    custom_list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_lists.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("films.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    served_since: Mapped[datetime] = mapped_column(default=utcnow)
    position: Mapped[int] = mapped_column(default=0)

    custom_list: Mapped[CustomList] = relationship(back_populates="items")
    film: Mapped[Film] = relationship()
