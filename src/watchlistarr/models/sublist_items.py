from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base, utcnow

if TYPE_CHECKING:
    from watchlistarr.models.films import Film
    from watchlistarr.models.sublists import Sublist


class SublistItem(Base):
    __tablename__ = "sublist_items"
    __table_args__ = (Index("ix_sublist_items_served_since", "sublist_id", "served_since"),)

    sublist_id: Mapped[int] = mapped_column(
        ForeignKey("sublists.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(
        ForeignKey("films.tmdb_id", ondelete="CASCADE"), primary_key=True
    )
    served_since: Mapped[datetime] = mapped_column(default=utcnow)
    position: Mapped[int] = mapped_column(default=0)

    sublist: Mapped[Sublist] = relationship(back_populates="items")
    film: Mapped[Film] = relationship()
