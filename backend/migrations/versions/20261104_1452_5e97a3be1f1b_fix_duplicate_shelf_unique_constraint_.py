"""fix duplicate shelf unique constraint names

The previous migration created both unique constraints of `shelves` under the same name
("uq_shelves_rack_id"), because the naming convention only uses the first column.
This rebuilds the table with distinct names:

    uq_shelves_rack_id_code   (rack_id, code)
    uq_shelves_rack_id_level  (rack_id, level)

The table definition is given explicitly (`copy_from`) instead of being read back from
the database, because reading it back would hit the ambiguous duplicate name.
All rows are copied; ids do not change, so bins keep pointing to their shelves.

Revision ID: 5e97a3be1f1b
Revises: c864c63ac8ba
Create Date: 2026-11-04 14:52:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e97a3be1f1b"
down_revision: str | Sequence[str] | None = "c864c63ac8ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _shelves_table(code_name: str, level_name: str) -> sa.Table:
    """The shelves table exactly as before, except for the two unique-constraint names."""
    metadata = sa.MetaData()
    sa.Table("racks", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    return sa.Table(
        "shelves",
        metadata,
        sa.Column("rack_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("level >= 1", name="ck_shelves_level_positive"),
        sa.ForeignKeyConstraint(
            ["rack_id"], ["racks.id"], name="fk_shelves_rack_id_racks", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shelves"),
        sa.UniqueConstraint("rack_id", "code", name=code_name),
        sa.UniqueConstraint("rack_id", "level", name=level_name),
        sa.Index("ix_shelves_rack_id", "rack_id"),
    )


def upgrade() -> None:
    """Rebuild `shelves` with distinct unique-constraint names."""
    with op.batch_alter_table(
        "shelves",
        recreate="always",
        copy_from=_shelves_table("uq_shelves_rack_id_code", "uq_shelves_rack_id_level"),
    ):
        pass


def downgrade() -> None:
    """Restore the previous (duplicate) names."""
    with op.batch_alter_table(
        "shelves",
        recreate="always",
        copy_from=_shelves_table("uq_shelves_rack_id", "uq_shelves_rack_id"),
    ):
        pass
