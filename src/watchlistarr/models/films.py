from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from watchlistarr.models.base import Base, utcnow


class Film(Base):
    __tablename__ = "films"

    tmdb_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    letterboxd_slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(nullable=True)
    tmdb_type: Mapped[str] = mapped_column(String(16), default="movie")
    letterboxd_avg_rating: Mapped[float | None] = mapped_column(nullable=True)
    last_resolved_at: Mapped[datetime] = mapped_column(default=utcnow)
