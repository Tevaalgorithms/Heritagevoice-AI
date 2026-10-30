"""who may read a published recording: its community only, or all signed-in users

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("recording", "evidence_chunk"):
        op.add_column(
            table,
            sa.Column("visibility", sa.String(16), nullable=False, server_default="community"),
        )
        op.create_index(f"ix_{table}_visibility", table, ["visibility"])


def downgrade() -> None:
    for table in ("evidence_chunk", "recording"):
        op.drop_index(f"ix_{table}_visibility", table_name=table)
        op.drop_column(table, "visibility")
