"""an English meaning for each name in a relationship

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("subject_en", "object_en"):
        op.add_column(
            "graph_assertion",
            sa.Column(column, sa.String(200), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_column("graph_assertion", "object_en")
    op.drop_column("graph_assertion", "subject_en")
