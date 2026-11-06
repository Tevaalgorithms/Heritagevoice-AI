"""who a recording is credited to and where its knowledge came from

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recording", sa.Column("credit_name", sa.String(100)))
    op.add_column("recording", sa.Column("source_kind", sa.String(16)))
    op.add_column("recording", sa.Column("source_note", sa.String(200)))


def downgrade() -> None:
    op.drop_column("recording", "source_note")
    op.drop_column("recording", "source_kind")
    op.drop_column("recording", "credit_name")
