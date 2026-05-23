"""swap sync cooldown for custom-list snapshot mode

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-23 19:00:00.000000

La migración 0007 añadió un cooldown sobre scrapes que no resolvía el problema
real del usuario (output de Radarr cambiando demasiado seguido por reordenamiento
de custom lists "top-N by rating"). Esta migración:

1. Dropea las columnas que añadió 0007 (`lists.min_sync_interval`,
   `users.watchlist_min_sync_interval`).
2. Añade el nuevo mecanismo: ``custom_lists.snapshot_interval`` (cadencia de
   regeneración completa del set) y ``custom_lists.last_snapshot_at`` (último
   refresh). NULL = modo legacy (comportamiento previo: re-orden al servir +
   rotation opcional).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.drop_column("min_sync_interval")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("watchlist_min_sync_interval")

    with op.batch_alter_table("custom_lists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("snapshot_interval", sa.Interval(), nullable=True))
        batch_op.add_column(sa.Column("last_snapshot_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("custom_lists", schema=None) as batch_op:
        batch_op.drop_column("last_snapshot_at")
        batch_op.drop_column("snapshot_interval")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("watchlist_min_sync_interval", sa.Interval(), nullable=True)
        )

    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("min_sync_interval", sa.Interval(), nullable=True))
