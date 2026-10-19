"""Postgres-backed raw object store (``XDATA_OBJECT_STORE_BACKEND=postgres``), write-once like the others.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_objects",
        sa.Column("key", sa.String(length=300), primary_key=True),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("data", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("CREATE TRIGGER raw_objects_immutable BEFORE UPDATE ON raw_objects "
               "FOR EACH ROW EXECUTE FUNCTION xdata_block_mutation()")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS raw_objects_immutable ON raw_objects")
    op.drop_table("raw_objects")
