"""model catalogue with statuses, and an ordered fall-back list per role

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

KEY_NAME = "HERITAGEVOICE_LLM_API_KEY"
SEED = ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")


def upgrade() -> None:
    catalog = op.create_table(
        "model_catalog",
        sa.Column("model_id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("key_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.bulk_insert(
        catalog,
        [{"model_id": m, "provider": "anthropic", "key_name": KEY_NAME} for m in SEED],
    )
    op.add_column(
        "model_setting", sa.Column("fallbacks", sa.JSON, nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.drop_column("model_setting", "fallbacks")
    op.drop_table("model_catalog")
