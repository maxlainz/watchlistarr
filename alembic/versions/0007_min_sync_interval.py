"""min sync interval (cooldown ceiling)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-23 12:00:00.000000

Añade un cooldown duro opcional por-lista que actúa como ceiling sobre
los intervalos del scheduler. Si ``now < last_synced_at + min_sync_interval``,
los jobs incremental/full skipean silenciosamente. Aplica a:
- ``lists.min_sync_interval`` para custom lists de Letterboxd
- ``users.watchlist_min_sync_interval`` para la watchlist del usuario

Ambas columnas son nullable; ``NULL`` significa "sin cooldown" (comportamiento
previo).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("min_sync_interval", sa.Interval(), nullable=True))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("watchlist_min_sync_interval", sa.Interval(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("watchlist_min_sync_interval")

    with op.batch_alter_table("lists", schema=None) as batch_op:
        batch_op.drop_column("min_sync_interval")
