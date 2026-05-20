from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Interval, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base, utcnow

if TYPE_CHECKING:
    from watchlistarr.models.lists import List
    from watchlistarr.models.sublists import Sublist


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    letterboxd_username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    added_at: Mapped[datetime] = mapped_column(default=utcnow)

    rss_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    watchlist_incremental_interval: Mapped[timedelta | None] = mapped_column(
        Interval, nullable=True
    )
    watchlist_full_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    films_backstop_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    discovery_interval: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)

    lists: Mapped[list[List]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sublists: Mapped[list[Sublist]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
