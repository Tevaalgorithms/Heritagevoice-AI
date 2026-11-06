"""Records the platform keeps: recordings, consent, versions, review decisions, graph assertions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.credit import SourceKind
from app.models.transcript import Segment


class Right(StrEnum):
    """Each right is granted separately; none implies another."""

    PLAYBACK = "playback"
    AI_PROCESSING = "ai_processing"
    TRANSLATION = "translation"
    INDEXING = "indexing"
    SUMMARIZATION = "summarization"
    ATTRIBUTION = "attribution"
    PUBLIC_SHARING = "public_sharing"


class Consent(BaseModel):
    """What a community has allowed for a recording, and whether it was withdrawn."""

    model_config = ConfigDict(frozen=True)
    id: str
    community_id: str
    rights: frozenset[Right]
    policy_version: str
    revoked: bool = False

    def permits(self, right: Right) -> bool:
        return not self.revoked and right in self.rights


class RecordingStatus(StrEnum):
    """Where a recording is in its life, from draft to published or revoked."""

    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    REVOKED = "revoked"


class HeritageKind(StrEnum):
    """What a recording holds. Remedies are health-related: never present them as advice."""

    STORY = "story"
    SONG = "song"
    LESSON = "lesson"
    PRACTICE = "practice"
    REMEDY = "remedy"


class Visibility(StrEnum):
    """Who may read a published recording. Public is never the default: it needs the community's
    `public_sharing` consent and an admin's approval, and it reaches signed-in users only."""

    COMMUNITY = "community"
    PUBLIC = "public"


REMEDY_NOTICE = "Not medically validated. Shared from the traditional notes of elders."


class Recording(BaseModel):
    """A recorded piece of heritage and its processing state."""

    model_config = ConfigDict(frozen=True)
    id: str
    community_id: str
    uploader_id: str
    language: str
    consent_id: str
    heritage_kind: HeritageKind = HeritageKind.STORY
    visibility: Visibility = Visibility.COMMUNITY
    status: RecordingStatus = RecordingStatus.DRAFT
    audio_key: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    credit_name: str | None = None
    source_kind: SourceKind | None = None
    source_note: str | None = None
    added: str = ""  # the day it was added, YYYY-MM-DD; set when read, never stored directly


class VersionStatus(StrEnum):
    """Whether a transcript or translation version is a draft or approved."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TranscriptVersion(BaseModel):
    """A version of a recording's transcript."""

    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    version: int = Field(ge=1)
    status: VersionStatus = VersionStatus.DRAFT
    segments: list[Segment]
    created_by: str


class TranslationVersion(BaseModel):
    """A version of a recording's translation."""

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
    """What a review decision is about: the transcript or the translation."""

    TRANSCRIPT = "transcript"
    TRANSLATION = "translation"
    ASSERTION = "assertion"


class VersionRef(BaseModel):
    """A transcript or translation version, as the review workflow sees it."""

    model_config = ConfigDict(frozen=True)
    kind: Subject
    version: int = Field(ge=1)
    status: VersionStatus
    segments: list[Segment]
    transcript_version: int | None = None  # set for translations: the transcript they translate


class ReviewDecision(BaseModel):
    """A reviewer's decision on one version."""

    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    subject: Subject
    subject_version: int = Field(ge=1)
    reviewer_id: str
    approved: bool
    note: str | None = None


class Relation(StrEnum):
    """The kinds of relationship the knowledge graph can record."""

    SPOKE_IN = "SPOKE_IN"
    MENTIONS = "MENTIONS"
    DESCRIBES = "DESCRIBES"
    OCCURRED_AT = "OCCURRED_AT"
    RELATED_TO = "RELATED_TO"
    TEACHES = "TEACHES"
    SUPPORTED_BY = "SUPPORTED_BY"


RELATION_PHRASES = {
    Relation.MENTIONS: "mentions",
    Relation.DESCRIBES: "is about",
    Relation.OCCURRED_AT: "happened at",
    Relation.RELATED_TO: "is related to",
    Relation.TEACHES: "teaches",
    Relation.SPOKE_IN: "spoke in",
    Relation.SUPPORTED_BY: "is supported by",
}


def relation_phrase(code: str) -> str:
    """A relationship as words, for example `teaches`. Unknown ones are shown as stored."""
    try:
        return RELATION_PHRASES[Relation(code)]
    except ValueError:
        return code


def path_text(steps: tuple[str, ...]) -> str:
    """A graph path as a sentence: names at even places, relationships between them."""
    words = [relation_phrase(step) if index % 2 else step for index, step in enumerate(steps)]
    return " ".join(words)


class ReviewState(StrEnum):
    """Whether a graph assertion is pending, approved or rejected."""

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
    subject_en: str = ""  # what the two names mean in English, so English readers can follow
    object_en: str = ""
    asserted_by: str
    review_state: ReviewState = ReviewState.PENDING
    supporting_segment_id: str
    transcript_version: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    policy_ref: str


class ReportReason(StrEnum):
    """Why someone reported a recording."""

    PRIVATE = "private"
    HARMFUL = "harmful"
    HEALTH = "health"
    COPYRIGHT = "copyright"
    OTHER = "other"


class ReportStatus(StrEnum):
    """Where a report is: waiting for an admin, or decided."""

    OPEN = "open"
    TAKEN_DOWN = "taken_down"
    DISMISSED = "dismissed"


class ItemReport(BaseModel):
    """A report about a recording. The reporter's identity is for admins only."""

    model_config = ConfigDict(frozen=True)
    id: str
    recording_id: str
    reason: ReportReason
    note: str | None = None
    reporter: str | None = None  # the signed-in account, or None for a visitor
    status: ReportStatus = ReportStatus.OPEN
