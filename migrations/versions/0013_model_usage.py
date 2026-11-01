"""token usage per model call, and a price per model for the cost estimate

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_usage",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_model_usage_at", "model_usage", ["at"])
    op.add_column("model_catalog", sa.Column("input_price", sa.Float))
    op.add_column("model_catalog", sa.Column("output_price", sa.Float))


def downgrade() -> None:
    op.drop_column("model_catalog", "output_price")
    op.drop_column("model_catalog", "input_price")
    op.drop_table("model_usage")
