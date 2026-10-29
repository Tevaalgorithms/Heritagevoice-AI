"""records, consent, versions, review, graph assertions, users, audit log

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _pk(name: str = "id", length: int = 64) -> sa.Column:
    return sa.Column(name, sa.String(length), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "consent",
        _pk(),
        sa.Column("community_id", sa.String(64), nullable=False),
        sa.Column("rights", sa.JSON, nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False),
    )
    op.create_index("ix_consent_community_id", "consent", ["community_id"])
    op.create_table(
        "recording",
        _pk(),
        sa.Column("community_id", sa.String(64), nullable=False),
        sa.Column("uploader_id", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("consent_id", sa.String(64), sa.ForeignKey("consent.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("ix_recording_community_id", "recording", ["community_id"])
    op.create_index("ix_recording_status", "recording", ["status"])
    op.create_table(
        "transcript_version",
        _pk(),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("segments", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.UniqueConstraint("recording_id", "version"),
    )
    op.create_index("ix_transcript_version_recording_id", "transcript_version", ["recording_id"])
    op.create_table(
        "translation_version",
        _pk(),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("transcript_version", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("target_language", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("segments", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.UniqueConstraint("recording_id", "target_language", "version"),
    )
    op.create_index("ix_translation_version_recording_id", "translation_version", ["recording_id"])
    op.create_table(
        "review_decision",
        _pk(),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("subject", sa.String(16), nullable=False),
        sa.Column("subject_version", sa.Integer, nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("decided_at", TS, nullable=False),
    )
    op.create_index("ix_review_decision_recording_id", "review_decision", ["recording_id"])
    op.create_table(
        "graph_assertion",
        _pk(),
        sa.Column("recording_id", sa.String(64), sa.ForeignKey("recording.id"), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("object", sa.String(200), nullable=False),
        sa.Column("asserted_by", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(16), nullable=False),
        sa.Column("supporting_segment_id", sa.String(64), nullable=False),
        sa.Column("transcript_version", sa.Integer, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("policy_ref", sa.String(64), nullable=False),
    )
    op.create_index("ix_graph_assertion_recording_id", "graph_assertion", ["recording_id"])
    op.create_index("ix_graph_assertion_review_state", "graph_assertion", ["review_state"])
    op.create_table(
        "app_user",
        _pk("sub"),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "community_member",
        sa.Column("user_sub", sa.String(64), sa.ForeignKey("app_user.sub"), primary_key=True),
        sa.Column("community_id", sa.String(64), primary_key=True),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_sub", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("at", TS, nullable=False),
    )


def downgrade() -> None:
    for table in (
        "audit_log",
        "community_member",
        "app_user",
        "graph_assertion",
        "review_decision",
        "translation_version",
        "transcript_version",
        "recording",
        "consent",
    ):
        op.drop_table(table)
