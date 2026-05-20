"""custom lists multi-source

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20 18:00:00.000000

Rediseño del modelo de sublistas:
- Renombra sublists → custom_lists, sublist_items → custom_list_items.
- Elimina parent_list_id / parent_combined_kind y los enums combinados.
- Introduce custom_list_sources (multi-origen con role include/subtract) y
  custom_list_excluded_watchers (vistos a excluir).
- Migra datos existentes: cada sublist con parent_list_id → 1 source include;
  combinadas union/intersection/union-unwatched → sources = todas las watchlists
  con op correspondiente (y excluded_watchers = todos los users para
  union-unwatched).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "custom_lists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "op",
            sa.Enum("union", "intersection", name="combination_op_enum"),
            nullable=False,
            server_default="union",
        ),
        sa.Column("max_items", sa.Integer(), nullable=True),
        sa.Column(
            "sort_order",
            sa.Enum("letterboxd", "random", "reverse", name="sort_order_enum"),
            nullable=False,
        ),
        sa.Column("min_rating", sa.Float(), nullable=True),
        sa.Column("max_rating", sa.Float(), nullable=True),
        sa.Column("min_year", sa.Integer(), nullable=True),
        sa.Column("max_year", sa.Integer(), nullable=True),
        sa.Column("added_after", sa.DateTime(), nullable=True),
        sa.Column("added_before", sa.DateTime(), nullable=True),
        sa.Column("rotation_enabled", sa.Boolean(), nullable=False),
        sa.Column("rotation_interval", sa.Interval(), nullable=True),
        sa.Column("rotation_batch_size", sa.Integer(), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_custom_lists_slug"),
    )
    with op.batch_alter_table("custom_lists", schema=None) as batch_op:
        batch_op.create_index("ix_custom_lists_slug", ["slug"], unique=False)

    op.create_table(
        "custom_list_items",
        sa.Column("custom_list_id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("served_since", sa.DateTime(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tmdb_id"], ["films.tmdb_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("custom_list_id", "tmdb_id"),
    )
    with op.batch_alter_table("custom_list_items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_custom_list_items_served_since",
            ["custom_list_id", "served_since"],
            unique=False,
        )

    op.create_table(
        "custom_list_sources",
        sa.Column("custom_list_id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("include", "subtract", name="source_role_enum"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("custom_list_id", "list_id", "role"),
    )
    with op.batch_alter_table("custom_list_sources", schema=None) as batch_op:
        batch_op.create_index("ix_custom_list_sources_list_id", ["list_id"], unique=False)

    op.create_table(
        "custom_list_excluded_watchers",
        sa.Column("custom_list_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["custom_list_id"], ["custom_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("custom_list_id", "user_id"),
    )

    # ---- Data migration ----
    sublists_meta = sa.Table(
        "sublists",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("user_id", sa.Integer()),
        sa.Column("parent_list_id", sa.Integer()),
        sa.Column("parent_combined_kind", sa.String()),
        sa.Column("slug", sa.String()),
        sa.Column("name", sa.String()),
        sa.Column("max_items", sa.Integer()),
        sa.Column("sort_order", sa.String()),
        sa.Column("min_rating", sa.Float()),
        sa.Column("max_rating", sa.Float()),
        sa.Column("min_year", sa.Integer()),
        sa.Column("max_year", sa.Integer()),
        sa.Column("added_after", sa.DateTime()),
        sa.Column("added_before", sa.DateTime()),
        sa.Column("rotation_enabled", sa.Boolean()),
        sa.Column("rotation_interval", sa.Interval()),
        sa.Column("rotation_batch_size", sa.Integer()),
        sa.Column("last_rotated_at", sa.DateTime()),
        sa.Column("enabled", sa.Boolean()),
    )

    sublist_items_meta = sa.Table(
        "sublist_items",
        sa.MetaData(),
        sa.Column("sublist_id", sa.Integer()),
        sa.Column("tmdb_id", sa.Integer()),
        sa.Column("served_since", sa.DateTime()),
        sa.Column("position", sa.Integer()),
    )

    lists_meta = sa.Table(
        "lists",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("user_id", sa.Integer()),
        sa.Column("source_type", sa.String()),
        sa.Column("slug", sa.String()),
    )

    users_meta = sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Integer()),
        sa.Column("letterboxd_username", sa.String()),
    )

    watchlist_ids = [
        row[0]
        for row in bind.execute(
            sa.select(lists_meta.c.id).where(lists_meta.c.source_type == "watchlist")
        ).fetchall()
    ]
    all_user_ids = [row[0] for row in bind.execute(sa.select(users_meta.c.id)).fetchall()]

    sublists_rows = bind.execute(sa.select(sublists_meta)).mappings().all()

    # Map old sublist.id -> new custom_list.id
    id_map: dict[int, int] = {}
    used_slugs: set[str] = set()

    def _unique_slug(base: str, owner_username: str | None) -> str:
        candidate = base
        if owner_username and candidate in used_slugs:
            candidate = f"{owner_username}-{base}"
        i = 2
        while candidate in used_slugs:
            candidate = f"{base}-{i}"
            i += 1
        used_slugs.add(candidate)
        return candidate

    # Build user_id -> username map for slug disambiguation
    username_by_user_id: dict[int, str] = {
        row[0]: row[1]
        for row in bind.execute(
            sa.select(users_meta.c.id, users_meta.c.letterboxd_username)
        ).fetchall()
    }

    for row in sublists_rows:
        owner = (
            username_by_user_id.get(row["user_id"]) if row["user_id"] is not None else None
        )
        new_slug = _unique_slug(row["slug"], owner)
        insert = sa.insert(
            sa.table(
                "custom_lists",
                sa.column("slug", sa.String()),
                sa.column("name", sa.String()),
                sa.column("op", sa.String()),
                sa.column("max_items", sa.Integer()),
                sa.column("sort_order", sa.String()),
                sa.column("min_rating", sa.Float()),
                sa.column("max_rating", sa.Float()),
                sa.column("min_year", sa.Integer()),
                sa.column("max_year", sa.Integer()),
                sa.column("added_after", sa.DateTime()),
                sa.column("added_before", sa.DateTime()),
                sa.column("rotation_enabled", sa.Boolean()),
                sa.column("rotation_interval", sa.Interval()),
                sa.column("rotation_batch_size", sa.Integer()),
                sa.column("last_rotated_at", sa.DateTime()),
                sa.column("enabled", sa.Boolean()),
            )
        )
        kind = row["parent_combined_kind"]
        op_value = "intersection" if kind == "intersection" else "union"
        result = bind.execute(
            insert.values(
                slug=new_slug,
                name=row["name"],
                op=op_value,
                max_items=row["max_items"],
                sort_order=row["sort_order"],
                min_rating=row["min_rating"],
                max_rating=row["max_rating"],
                min_year=row["min_year"],
                max_year=row["max_year"],
                added_after=row["added_after"],
                added_before=row["added_before"],
                rotation_enabled=row["rotation_enabled"],
                rotation_interval=row["rotation_interval"],
                rotation_batch_size=row["rotation_batch_size"],
                last_rotated_at=row["last_rotated_at"],
                enabled=row["enabled"],
            )
        )
        inserted_pk = result.inserted_primary_key
        if inserted_pk and inserted_pk[0] is not None:
            new_id = inserted_pk[0]
        else:
            new_id = result.lastrowid
        id_map[row["id"]] = new_id

        if row["parent_list_id"] is not None:
            bind.execute(
                sa.insert(
                    sa.table(
                        "custom_list_sources",
                        sa.column("custom_list_id", sa.Integer()),
                        sa.column("list_id", sa.Integer()),
                        sa.column("role", sa.String()),
                    )
                ).values(
                    custom_list_id=new_id, list_id=row["parent_list_id"], role="include"
                )
            )
        elif kind in {"union", "intersection", "union-unwatched"}:
            for wl_id in watchlist_ids:
                bind.execute(
                    sa.insert(
                        sa.table(
                            "custom_list_sources",
                            sa.column("custom_list_id", sa.Integer()),
                            sa.column("list_id", sa.Integer()),
                            sa.column("role", sa.String()),
                        )
                    ).values(custom_list_id=new_id, list_id=wl_id, role="include")
                )
            if kind == "union-unwatched":
                for uid in all_user_ids:
                    bind.execute(
                        sa.insert(
                            sa.table(
                                "custom_list_excluded_watchers",
                                sa.column("custom_list_id", sa.Integer()),
                                sa.column("user_id", sa.Integer()),
                            )
                        ).values(custom_list_id=new_id, user_id=uid)
                    )

    # Migrate sublist_items rows
    items_rows = bind.execute(sa.select(sublist_items_meta)).mappings().all()
    for item in items_rows:
        new_id = id_map.get(item["sublist_id"])
        if new_id is None:
            continue
        bind.execute(
            sa.insert(
                sa.table(
                    "custom_list_items",
                    sa.column("custom_list_id", sa.Integer()),
                    sa.column("tmdb_id", sa.Integer()),
                    sa.column("served_since", sa.DateTime()),
                    sa.column("position", sa.Integer()),
                )
            ).values(
                custom_list_id=new_id,
                tmdb_id=item["tmdb_id"],
                served_since=item["served_since"],
                position=item["position"],
            )
        )

    # Drop old tables
    with op.batch_alter_table("sublist_items", schema=None) as batch_op:
        batch_op.drop_index("ix_sublist_items_served_since")
    op.drop_table("sublist_items")

    with op.batch_alter_table("sublists", schema=None) as batch_op:
        batch_op.drop_index("uq_sublists_user_slug")
        batch_op.drop_index("uq_sublists_combined_slug")
        batch_op.drop_index("ix_sublists_user_id")
        batch_op.drop_index("ix_sublists_parent_list_id")
    op.drop_table("sublists")


def downgrade() -> None:
    """No reversible migration: la pérdida de información (varios sources →
    un único parent) hace que el downgrade no sea fielmente representable.
    Para revertir, restaurar desde backup."""
    raise NotImplementedError("downgrade not supported for 0003")
