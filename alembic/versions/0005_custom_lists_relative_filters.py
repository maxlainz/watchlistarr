"""custom_lists.year_last_n / added_last_n_days

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-21 13:00:00.000000

Añade dos columnas a ``custom_lists`` para soportar ventanas de filtro
**relativas a ``utcnow()``** que no necesitan editarse al cambiar el año:

- ``year_last_n``: cuando no es NULL, se ignoran ``min_year``/``max_year`` y se
  filtra por ``year ∈ [current_year - N + 1, current_year]``.
- ``added_last_n_days``: cuando no es NULL, se ignoran
  ``added_after``/``added_before`` y se filtra por
  ``added_at >= utcnow() - N days``.

El front fuerza exclusión mutua, pero el back también la blinda al guardar.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("custom_lists", schema=None) as batch_op:
        batch_op.add_column(sa.Column("year_last_n", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("added_last_n_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("custom_lists", schema=None) as batch_op:
        batch_op.drop_column("added_last_n_days")
        batch_op.drop_column("year_last_n")
