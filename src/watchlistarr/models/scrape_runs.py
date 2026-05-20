from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from watchlistarr.models.base import Base, utcnow
from watchlistarr.models.enums import ScrapeSource, ScrapeStatus


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (
        Index("ix_scrape_runs_source_started", "source", "started_at"),
        Index("ix_scrape_runs_target", "target_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[ScrapeSource] = mapped_column(
        SAEnum(
            ScrapeSource,
            name="scrape_source_enum",
            values_callable=lambda obj: [e.value for e in obj],
        )
    )
    target_id: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[ScrapeStatus] = mapped_column(
        SAEnum(
            ScrapeStatus,
            name="scrape_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ScrapeStatus.RUNNING,
    )
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
