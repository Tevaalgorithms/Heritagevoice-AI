"""reports about recordings, for an admin to decide

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_report",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("reporter", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_by", sa.String(64)),
    )
    op.create_index("ix_item_report_recording_id", "item_report", ["recording_id"])
    op.create_index("ix_item_report_status", "item_report", ["status"])


def downgrade() -> None:
    op.drop_table("item_report")
