"""add the OpenAI models to the model catalogue

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

KEY_NAME = "OPENAI_API_KEY"
MODELS = ("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano")


def upgrade() -> None:
    bind = op.get_bind()
    for model in MODELS:
        exists = bind.execute(
            sa.text("SELECT 1 FROM model_catalog WHERE model_id = :m"), {"m": model}
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO model_catalog (model_id, provider, key_name) "
                    "VALUES (:m, 'openai', :k)"
                ),
                {"m": model, "k": KEY_NAME},
            )


def downgrade() -> None:
    for model in MODELS:
        op.execute(sa.text("DELETE FROM model_catalog WHERE model_id = :m").bindparams(m=model))
