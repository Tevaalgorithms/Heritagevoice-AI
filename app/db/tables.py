"""SQLAlchemy tables. Domain models live in app/models; rows never leave the repositories."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class JobRow(Base):
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
    __tablename__ = "consent"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    rights: Mapped[list[str]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(32))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class RecordingRow(Base):
    __tablename__ = "recording"
    __table_args__ = (UniqueConstraint("uploader_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    uploader_id: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))
    consent_id: Mapped[str] = mapped_column(ForeignKey("consent.id"))
    status: Mapped[str] = mapped_column(String(16), index=True)
    audio_key: Mapped[str | None] = mapped_column(String(256), default=None)
    content_type: Mapped[str | None] = mapped_column(String(64), default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_s: Mapped[float | None] = mapped_column(Float, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TranscriptVersionRow(Base):
    __tablename__ = "transcript_version"
    __table_args__ = (UniqueConstraint("recording_id", "version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))


class TranslationVersionRow(Base):
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
    __tablename__ = "graph_assertion"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    relation: Mapped[str] = mapped_column(String(16))
    object: Mapped[str] = mapped_column(String(200))
    asserted_by: Mapped[str] = mapped_column(String(64))
    review_state: Mapped[str] = mapped_column(String(16), index=True)
    supporting_segment_id: Mapped[str] = mapped_column(String(64))
    transcript_version: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    policy_ref: Mapped[str] = mapped_column(String(64))


class AppUserRow(Base):
    __tablename__ = "app_user"

    sub: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CommunityMemberRow(Base):
    __tablename__ = "community_member"

    user_sub: Mapped[str] = mapped_column(ForeignKey("app_user.sub"), primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), primary_key=True)


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
