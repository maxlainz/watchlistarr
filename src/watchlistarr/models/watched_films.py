from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from watchlistarr.models.base import Base, utcnow
from watchlistarr.models.enums import WatchedSource


class WatchedFilm(Base):
    __tablename__ = "watched_films"
    __table_args__ = (Index("ix_watched_films_tmdb", "tmdb_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    first_seen_watched_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_watched_at: Mapped[datetime] = mapped_column(default=utcnow)
    source: Mapped[WatchedSource] = mapped_column(
        SAEnum(
            WatchedSource,
            name="watched_source_enum",
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
