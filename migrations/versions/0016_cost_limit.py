"""a monthly spending limit for the language models, set on the Settings page

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_limit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("monthly_usd", sa.Float, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cost_limit")
