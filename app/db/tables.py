"""SQLAlchemy tables. Domain models live in app/models; rows never leave the repositories."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all database tables."""

    pass


class JobRow(Base):
    """Database table for background jobs."""

    __tablename__ = "job"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(String(64), default=None)
    stage: Mapped[str | None] = mapped_column(String(32), default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    recording_id: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ConsentRow(Base):
    """Database table for consent records."""

    __tablename__ = "consent"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    rights: Mapped[list[str]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(32))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RecordingRow(Base):
    """Database table for recordings."""

    __tablename__ = "recording"
    __table_args__ = (UniqueConstraint("uploader_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    uploader_id: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))
    consent_id: Mapped[str] = mapped_column(ForeignKey("consent.id"))
    heritage_kind: Mapped[str] = mapped_column(String(16), default="story", server_default="story")
    visibility: Mapped[str] = mapped_column(
        String(16), default="community", server_default="community", index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)
    audio_key: Mapped[str | None] = mapped_column(String(256), default=None)
    content_type: Mapped[str | None] = mapped_column(String(64), default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)
    # Optional, given by the contributor; shown only when the consent includes attribution.
    credit_name: Mapped[str | None] = mapped_column(String(100), default=None)
    source_kind: Mapped[str | None] = mapped_column(String(16), default=None)
    source_note: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TranscriptVersionRow(Base):
    """Database table for transcript versions."""

    __tablename__ = "transcript_version"
    __table_args__ = (UniqueConstraint("recording_id", "version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))


class TranslationVersionRow(Base):
    """Database table for translation versions."""

    __tablename__ = "translation_version"
    __table_args__ = (UniqueConstraint("recording_id", "target_language", "version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    transcript_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    target_language: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))


class ReviewDecisionRow(Base):
    """Database table for review decisions."""

    __tablename__ = "review_decision"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    subject: Mapped[str] = mapped_column(String(16))
    subject_version: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[str] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GraphAssertionRow(Base):
    """Database table for reviewed knowledge-graph assertions (source of truth for Neo4j)."""

    __tablename__ = "graph_assertion"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    relation: Mapped[str] = mapped_column(String(16))
    object: Mapped[str] = mapped_column(String(200))
    subject_en: Mapped[str] = mapped_column(String(200), default="", server_default="")
    object_en: Mapped[str] = mapped_column(String(200), default="", server_default="")
    asserted_by: Mapped[str] = mapped_column(String(64))
    review_state: Mapped[str] = mapped_column(String(16), index=True)
    supporting_segment_id: Mapped[str] = mapped_column(String(64))
    transcript_version: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    policy_ref: Mapped[str] = mapped_column(String(64))


class AppUserRow(Base):
    """Database table for users."""

    __tablename__ = "app_user"

    sub: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CommunityMemberRow(Base):
    """Database table linking users to communities."""

    __tablename__ = "community_member"

    user_sub: Mapped[str] = mapped_column(ForeignKey("app_user.sub"), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class CommunityRow(Base):
    """A group of people who share heritage: an ID for the code and a friendly name for people."""

    __tablename__ = "community"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ItemReportRow(Base):
    """A report about a recording, for an admin to decide."""

    __tablename__ = "item_report"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    reason: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    reporter: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(16), index=True, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_by: Mapped[str | None] = mapped_column(String(64), default=None)


class AuditLogRow(Base):
    """Who did what to whom. Never stores transcript or recording content."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_sub: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128))
    trace_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(200), default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelCatalogRow(Base):
    """The models admins have approved. Holds the *name* of the key, never its value."""

    __tablename__ = "model_catalog"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    key_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # US dollars per million tokens, set by an admin; empty until they enter the provider's price.
    input_price: Mapped[float | None] = mapped_column(Float, default=None)
    output_price: Mapped[float | None] = mapped_column(Float, default=None)


class ModelUsageRow(Base):
    """One language-model call: which job and model, and how many tokens. Never any text."""

    __tablename__ = "model_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    role: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class CostLimitRow(Base):
    """The one monthly spending limit an admin set, in US dollars. No row means no limit."""

    __tablename__ = "cost_limit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    monthly_usd: Mapped[float] = mapped_column(Float)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ModelSettingRow(Base):
    """Admin-chosen model parameters per role. Never holds an API key."""

    __tablename__ = "model_setting"

    role: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    temperature: Mapped[float] = mapped_column(Float)
    timeout_s: Mapped[float] = mapped_column(Float)
    max_retries: Mapped[int] = mapped_column(Integer)
    fallbacks: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    updated_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class EvidenceChunkRow(Base):
    """Searchable chunks of approved content; removed at once on correction or revocation."""

    __tablename__ = "evidence_chunk"

    evidence_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    passage_hash: Mapped[str] = mapped_column(String(64))
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    segment_ids: Mapped[list[str]] = mapped_column(JSON)
    speaker: Mapped[str | None] = mapped_column(String(64), default=None)
    visibility: Mapped[str] = mapped_column(
        String(16), default="community", server_default="community", index=True
    )
