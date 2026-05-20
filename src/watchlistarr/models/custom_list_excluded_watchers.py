from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from watchlistarr.models.base import Base

if TYPE_CHECKING:
    from watchlistarr.models.custom_lists import CustomList
    from watchlistarr.models.users import User


class CustomListExcludedWatcher(Base):
    __tablename__ = "custom_list_excluded_watchers"

    custom_list_id: Mapped[int] = mapped_column(
        ForeignKey("custom_lists.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    custom_list: Mapped[CustomList] = relationship(back_populates="excluded_watchers")
    user: Mapped[User] = relationship()
