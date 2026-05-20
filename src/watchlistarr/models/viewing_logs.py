from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from watchlistarr.models.base import Base, utcnow


class ViewingLog(Base):
    __tablename__ = "viewing_logs"

    letterboxd_guid: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tmdb_id: Mapped[int] = mapped_column(index=True)
    watched_date: Mapped[date] = mapped_column()
    rating: Mapped[float | None] = mapped_column(nullable=True)
    member_like: Mapped[bool] = mapped_column(default=False)
    recorded_at: Mapped[datetime] = mapped_column(default=utcnow)
