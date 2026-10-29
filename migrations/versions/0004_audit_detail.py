"""audit log detail (short reason for revocations)

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.add_column(sa.Column("detail", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.drop_column("detail")
