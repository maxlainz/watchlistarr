"""sort_order enum: add rating_desc value

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-22 11:00:00.000000

La migración 0003 creó ``sort_order_enum`` solo con
``('letterboxd', 'random', 'reverse')``, pero el modelo declara también
``SortOrder.RATING_DESC = 'rating_desc'``. En SQLite los enums son strings
sin check constraint y nunca se notó; en Postgres cualquier INSERT/UPDATE
con ``sort_order='rating_desc'`` falla con ``invalid input value for enum``.

Esta revisión añade el valor al enum nativo de Postgres. En SQLite no es
necesaria — los enums se serializan como VARCHAR — así que la migración
hace no-op para ese dialecto.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE no se puede ejecutar dentro de un bloque
        # transaccional en versiones antiguas; alembic abre la transacción,
        # pero Postgres 12+ lo permite si la transacción no contiene otros
        # comandos sobre el mismo tipo.
        op.execute("ALTER TYPE sort_order_enum ADD VALUE IF NOT EXISTS 'rating_desc'")


def downgrade() -> None:
    # Postgres no permite eliminar valores de un enum sin recrear el tipo.
    # Como la pérdida de información (filas con sort_order='rating_desc')
    # no es reversible fielmente, este downgrade queda como no-op.
    pass
