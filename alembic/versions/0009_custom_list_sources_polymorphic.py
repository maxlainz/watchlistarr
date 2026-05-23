"""custom_list_sources polimórfico: permite custom lists como source

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-23 21:00:00.000000

Hasta 0008, ``custom_list_sources`` solo apuntaba a ``lists`` vía ``list_id``
NOT NULL. Esta migración la abre para que ``source_custom_list_id`` (nullable,
FK a ``custom_lists``) sea otra forma de origen — exactamente uno de los dos
columnas debe estar set (CHECK constraint).

Cambios:
- Reemplaza la PK compuesta ``(custom_list_id, list_id, role)`` por una
  surrogate ``id``.
- ``list_id`` pasa a nullable.
- Nueva columna ``source_custom_list_id`` (nullable, FK custom_lists.id,
  ON DELETE CASCADE).
- Dos UNIQUE constraints separadas para evitar duplicados según el tipo de
  origen: ``(custom_list_id, role, list_id)`` y ``(custom_list_id, role,
  source_custom_list_id)``.

Los datos existentes se preservan: todas las filas viejas tienen ``list_id``
set y reciben un ``id`` autoincrement nuevo.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Crear tabla nueva con el esquema final.
    op.create_table(
        "custom_list_sources_new",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("custom_list_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("include", "subtract", name="source_role_enum"),
            nullable=False,
        ),
        sa.Column("list_id", sa.Integer(), nullable=True),
        sa.Column("source_custom_list_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "custom_list_id", "role", "list_id", name="uq_custom_list_sources_list"
        ),
        sa.UniqueConstraint(
            "custom_list_id",
            "role",
            "source_custom_list_id",
            name="uq_custom_list_sources_custom_list",
        ),
        sa.CheckConstraint(
            "(list_id IS NOT NULL AND source_custom_list_id IS NULL) OR "
            "(list_id IS NULL AND source_custom_list_id IS NOT NULL)",
            name="ck_custom_list_sources_target_exactly_one",
        ),
    )

    # 2) Copiar filas existentes (todas con list_id set).
    bind.execute(
        sa.text(
            "INSERT INTO custom_list_sources_new "
            "(custom_list_id, role, list_id, source_custom_list_id) "
            "SELECT custom_list_id, role, list_id, NULL "
            "FROM custom_list_sources"
        )
    )

    # 3) Drop la tabla vieja + renombrar la nueva.
    op.drop_table("custom_list_sources")
    op.rename_table("custom_list_sources_new", "custom_list_sources")

    # 4) Índices secundarios.
    with op.batch_alter_table("custom_list_sources", schema=None) as batch_op:
        batch_op.create_index(
            "ix_custom_list_sources_custom_list_id",
            ["custom_list_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_custom_list_sources_list_id", ["list_id"], unique=False
        )
        batch_op.create_index(
            "ix_custom_list_sources_source_custom_list_id",
            ["source_custom_list_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM custom_list_sources "
            "WHERE source_custom_list_id IS NOT NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"downgrade 0009: hay {count} fila(s) con source_custom_list_id; "
            "elimínalas antes de hacer downgrade."
        )

    op.create_table(
        "custom_list_sources_old",
        sa.Column("custom_list_id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("include", "subtract", name="source_role_enum"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("custom_list_id", "list_id", "role"),
    )
    bind.execute(
        sa.text(
            "INSERT INTO custom_list_sources_old (custom_list_id, list_id, role) "
            "SELECT custom_list_id, list_id, role FROM custom_list_sources"
        )
    )
    op.drop_table("custom_list_sources")
    op.rename_table("custom_list_sources_old", "custom_list_sources")
    with op.batch_alter_table("custom_list_sources", schema=None) as batch_op:
        batch_op.create_index(
            "ix_custom_list_sources_list_id", ["list_id"], unique=False
        )
