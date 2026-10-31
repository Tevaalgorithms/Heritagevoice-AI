"""a friendly name for each group; groups already in use are named after their ID

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO community (id, name) "
        "SELECT DISTINCT community_id, community_id FROM ("
        "SELECT community_id FROM community_member "
        "UNION SELECT community_id FROM consent "
        "UNION SELECT community_id FROM recording) AS used"
    )


def downgrade() -> None:
    op.drop_table("community")
