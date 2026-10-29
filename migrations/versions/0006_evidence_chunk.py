"""searchable chunks of approved content, with a PostgreSQL full-text index

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

FTS_INDEX = "ix_evidence_chunk_fts"


def upgrade() -> None:
    op.create_table(
        "evidence_chunk",
        sa.Column("evidence_id", sa.String(200), primary_key=True),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("community_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("passage_hash", sa.String(64), nullable=False),
        sa.Column("start_s", sa.Float, nullable=False),
        sa.Column("end_s", sa.Float, nullable=False),
        sa.Column("segment_ids", sa.JSON, nullable=False),
        sa.Column("speaker", sa.String(64), nullable=True),
    )
    op.create_index("ix_evidence_chunk_recording_id", "evidence_chunk", ["recording_id"])
    op.create_index("ix_evidence_chunk_community_id", "evidence_chunk", ["community_id"])
    if op.get_bind().dialect.name == "postgresql":
        # The 'simple' configuration keeps Tamil words whole (tested), unlike a Python \w split.
        op.execute(
            f"CREATE INDEX {FTS_INDEX} ON evidence_chunk USING gin (to_tsvector('simple', text))"
        )


def downgrade() -> None:
    op.drop_table("evidence_chunk")
