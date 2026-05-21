"""films.imdb_id

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21 12:00:00.000000

Añade ``films.imdb_id`` (string nullable, unique parcial). Necesario porque el
parser de Radarr para "Custom List" (StevenLuParser.cs) solo lee ``imdb_id`` y
``title``; ignora ``tmdb_id``. Sin este campo Radarr no resuelve películas y
devuelve "No results were returned from your import list".

Los films existentes quedan con NULL: el backfill se hace lazy en
``resolve_film`` (re-resuelve si ``imdb_id IS NULL``) o forzado vía
``scripts/backfill_imdb.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("films", schema=None) as batch_op:
        batch_op.add_column(sa.Column("imdb_id", sa.String(length=16), nullable=True))
        batch_op.create_index(
            "ix_films_imdb_id",
            ["imdb_id"],
            unique=True,
            sqlite_where=sa.text("imdb_id IS NOT NULL"),
        )


def downgrade() -> None:
    with op.batch_alter_table("films", schema=None) as batch_op:
        batch_op.drop_index("ix_films_imdb_id")
        batch_op.drop_column("imdb_id")
