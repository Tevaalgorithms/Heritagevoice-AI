"""recording audio metadata and idempotency key; job stage, attempts and recording link

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recording") as batch:
        batch.add_column(sa.Column("audio_key", sa.String(256), nullable=True))
        batch.add_column(sa.Column("content_type", sa.String(64), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.Integer, nullable=True))
        batch.add_column(sa.Column("duration_s", sa.Float, nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_recording_uploader_idempotency", ["uploader_id", "idempotency_key"]
        )
    with op.batch_alter_table("job") as batch:
        batch.add_column(sa.Column("stage", sa.String(32), nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("recording_id", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.drop_column("recording_id")
        batch.drop_column("attempts")
        batch.drop_column("stage")
    with op.batch_alter_table("recording") as batch:
        batch.drop_constraint("uq_recording_uploader_idempotency", type_="unique")
        for column in ("idempotency_key", "duration_s", "size_bytes", "content_type", "audio_key"):
            batch.drop_column(column)
