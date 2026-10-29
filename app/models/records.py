"""Records the platform keeps: recordings, consent, versions, review decisions, graph assertions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.transcript import Segment


class Right(StrEnum):
    """Each right is granted separately; none implies another."""

    PLAYBACK = "playback"
    AI_PROCESSING = "ai_processing"
    TRANSLATION = "translation"
    INDEXING = "indexing"
    SUMMARIZATION = "summarization"
    ATTRIBUTION = "attribution"


class Consent(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    community_id: str
    rights: frozenset[Right]
    policy_version: str
    revoked: bool = False

    def permits(self, right: Right) -> bool:
        return not self.revoked and right in self.rights


class RecordingStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    REVOKED = "revoked"


class Recording(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    community_id: str
    uploader_id: str
    language: str
    consent_id: str
    status: RecordingStatus = RecordingStatus.DRAFT


class VersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TranscriptVersion(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    version: int = Field(ge=1)
    status: VersionStatus = VersionStatus.DRAFT
    segments: list[Segment]
    created_by: str


class TranslationVersion(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    transcript_version: int = Field(ge=1)
    version: int = Field(ge=1)
    target_language: str
    status: VersionStatus = VersionStatus.DRAFT
    segments: list[Segment]
    created_by: str


class Subject(StrEnum):
    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"
    ASSERTION = "assertion"


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    subject: Subject
    subject_version: int = Field(ge=1)
    reviewer_id: str
    approved: bool
    note: str | None = None


class Relation(StrEnum):
    SPOKE_IN = "SPOKE_IN"
    MENTIONS = "MENTIONS"
    DESCRIBES = "DESCRIBES"
    OCCURRED_AT = "OCCURRED_AT"
    RELATED_TO = "RELATED_TO"
    SUPPORTED_BY = "SUPPORTED_BY"


class ReviewState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GraphAssertion(BaseModel):
    """A candidate or approved graph edge. Confidence never replaces review."""

    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    subject: str
    relation: Relation
    object: str
    asserted_by: str
    review_state: ReviewState = ReviewState.PENDING
    supporting_segment_id: str
    transcript_version: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    policy_ref: str
