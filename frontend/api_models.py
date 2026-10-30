"""Typed shapes exchanged with the HeritageVoice API (requests and responses)."""

from pydantic import BaseModel


class Health(BaseModel):
    """The API's liveness report."""

    status: str
    mode: str


class Readiness(BaseModel):
    """The API's readiness report, one entry per dependency."""

    ready: bool
    checks: dict[str, str]


class QueryResult(BaseModel):
    """The answer to a question."""

    status: str
    answer: str = ""
    request_id: str = ""


class UploadSpec(BaseModel):
    """What the Upload page sends: the audio and what it contains."""

    data: bytes
    language: str
    community_id: str
    consent_id: str
    heritage_kind: str = "story"
    visibility: str = "community"


class UploadResult(BaseModel):
    """The IDs of the new recording and its job."""

    recording_id: str
    job_id: str


class JobView(BaseModel):
    """The state of a processing job."""

    job_id: str
    status: str
    stage: str | None = None
    error: str | None = None
    recording_id: str | None = None


class SegmentView(BaseModel):
    """A timed piece of speech."""

    segment_id: str
    start_s: float
    end_s: float
    text: str
    speaker: str | None = None


class VersionView(BaseModel):
    """A version of a transcript or translation."""

    version: int
    status: str
    segments: list[SegmentView]


class RecordingView(BaseModel):
    """A recording with its transcript and translation."""

    id: str
    community_id: str
    language: str
    heritage_kind: str = "story"
    visibility: str = "community"
    status: str
    duration_s: float | None = None
    transcript: VersionView | None = None
    translation: VersionView | None = None


class RecordingSummary(BaseModel):
    """A recording as listed for reviewers."""

    id: str
    community_id: str
    language: str
    heritage_kind: str = "story"
    visibility: str = "community"
    status: str
    duration_s: float | None = None


class ReviewSpec(BaseModel):
    """What the Review page sends to approve or reject a version."""

    kind: str
    expected_version: int
    approved: bool
    note: str | None = None


class VersionResult(BaseModel):
    """The version created or decided by a review action."""

    kind: str
    version: int
    status: str


class MeView(BaseModel):
    """The signed-in user."""

    user_id: str
    role: str
    communities: list[str] = []


class ModelParamsSpec(BaseModel):
    """What the Settings page sends to save a job's models and limits."""

    provider: str
    model: str
    temperature: float = 0.0
    timeout_s: float = 30.0
    max_retries: int = 2
    fallbacks: list[str] = []


class CatalogView(BaseModel):
    """A catalogue model, with whether its key is configured."""

    model_id: str
    provider: str
    key_name: str
    status: str
    key_configured: bool


class NewModelSpec(BaseModel):
    """What the Settings page sends to add a model."""

    model_id: str
    provider: str
    key_name: str


class ModelView(BaseModel):
    """The model setting in force for one job."""

    role: str
    provider: str
    model: str
    temperature: float
    timeout_s: float
    max_retries: int
    source: str
    fallbacks: list[str] = []


class ModelsOverview(BaseModel):
    """The catalogue and every job's setting."""

    catalog: list[CatalogView]
    roles: list[ModelView]


class ProbeView(BaseModel):
    """The outcome of the Test button."""

    ok: bool
    code: str | None = None


class LibrarySpec(BaseModel):
    """What the Library page asks for. Empty fields mean "any"."""

    q: str = ""
    language: str = ""
    kind: str = ""
    view: str = "original"
    limit: int = 20


class LibraryItem(BaseModel):
    """One passage from the Library, with the notices that must be shown with it."""

    evidence_id: str
    recording_id: str
    heritage_kind: str
    language: str
    view: str
    passage: str
    start_s: float
    end_s: float
    notices: list[str] = []
    community: str | None = None


class LibraryResult(BaseModel):
    """The passages that matched."""

    items: list[LibraryItem]


class VisibilityResult(BaseModel):
    """A recording's visibility after an admin changed it."""

    recording_id: str
    visibility: str
