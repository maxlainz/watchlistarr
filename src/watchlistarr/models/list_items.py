from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base, utcnow

if TYPE_CHECKING:
    from watchlistarr.models.films import Film
    from watchlistarr.models.lists import List


class ListItem(Base):
    __tablename__ = "list_items"
    __table_args__ = (
        Index("ix_list_items_tmdb", "tmdb_id"),
        Index("ix_list_items_list_position", "list_id", "position"),
    )

    list_id: Mapped[int] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("films.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(default=0)
    added_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    pending_removal_count: Mapped[int] = mapped_column(default=0)

    list: Mapped[List] = relationship(back_populates="items")
    film: Mapped[Film] = relationship()
