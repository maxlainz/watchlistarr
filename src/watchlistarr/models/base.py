from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["Base", "MappedAsDataclass", "utcnow"]
