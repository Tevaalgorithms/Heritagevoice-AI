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


class CreditView(BaseModel):
    """Who to thank and where the knowledge came from, as far as the consent lets readers see."""

    name: str | None = None
    source_kind: str | None = None
    source_note: str | None = None


class CitationView(BaseModel):
    """A source for an answer: the passage and where it is in the recording."""

    evidence_id: str
    recording_id: str
    title: str
    passage: str
    start_s: float
    end_s: float
    notices: list[str] = []
    added: str = ""
    heritage_kind: str = ""
    language: str = ""
    credit: CreditView | None = None


class QueryResult(BaseModel):
    """The answer to a question, its sources, and how complete it is."""

    status: str
    answer: str = ""
    citations: list[CitationView] = []
    warnings: list[str] = []
    request_id: str = ""


class UploadSpec(BaseModel):
    """What the Upload page sends: the audio and what it contains."""

    data: bytes
    language: str
    community_id: str
    consent_id: str
    heritage_kind: str = "story"
    visibility: str = "community"
    credit_name: str = ""
    source_kind: str = ""
    source_note: str = ""


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
    added: str = ""
    credit: CreditView | None = None  # what the contributor entered
    credit_public: bool = False  # whether readers will see it


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


class SignupView(BaseModel):
    """Someone who created an account and is waiting for an administrator."""

    sub: str
    email: str
    created: str


class AccountView(BaseModel):
    """An account that has a role here. `email` is empty if the sign-in account no longer exists."""

    sub: str
    email: str = ""
    role: str
    status: str
    communities: list[str] = []
    created: str = ""
    is_you: bool = False


class GroupView(BaseModel):
    """A group: a family, a village, a choir. People see the name; the system uses the ID."""

    id: str
    name: str


class MemberView(BaseModel):
    """A person in a group."""

    sub: str
    email: str


class ConsentView(BaseModel):
    """What a group has allowed, and whether it was withdrawn."""

    id: str
    community_id: str
    rights: list[str]
    policy_version: str
    revoked: bool


class ConsentChoiceView(BaseModel):
    """A consent a contributor can pick when adding a recording."""

    id: str
    policy_version: str
    rights: list[str]


class MyGroupView(BaseModel):
    """A group the signed-in user belongs to, with its active consents."""

    id: str
    name: str
    consents: list[ConsentChoiceView] = []


class ReportView(BaseModel):
    """A report about a recording, as an admin sees it."""

    id: str
    recording_id: str
    reason: str
    note: str | None = None
    reporter: str
    heritage_kind: str
    language: str
    community: str
    recording_status: str
    opening: str = ""
    reports_for_recording: int = 1


class AssertionView(BaseModel):
    """A relationship proposed from a recording, with the words it came from."""

    id: str
    recording_id: str
    subject: str
    relation: str
    object: str
    asserted_by: str
    review_state: str
    confidence: float
    start_s: float | None = None
    end_s: float | None = None
    passage: str = ""


class AssertionEditSpec(BaseModel):
    """Corrections to a proposal; a field left as None stays as it was."""

    subject: str | None = None
    relation: str | None = None
    object: str | None = None


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
    input_price: float | None = None  # US dollars per million tokens
    output_price: float | None = None


class VoiceSuggestionView(BaseModel):
    """What a spoken correction was heard as, in the speaker's language and in English, and the
    relationship it was taken to mean (empty when nothing clear could be made of it)."""

    heard: str
    english: str
    understood: bool
    subject: str = ""
    relation: str | None = None
    object: str = ""


class UsageLine(BaseModel):
    """Calls, tokens and estimated cost of one job with one model."""

    role: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float | None = None


class UsageView(BaseModel):
    """The Usage page: every line, the totals, and the models still missing a price."""

    days: int
    lines: list[UsageLine]
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    unpriced_models: list[str]


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
    added: str = ""
    credit: CreditView | None = None


class LibraryResult(BaseModel):
    """The passages that matched."""

    items: list[LibraryItem]


class VisibilityResult(BaseModel):
    """A recording's visibility after an admin changed it."""

    recording_id: str
    visibility: str


class IntegrationItem(BaseModel):
    """One key or setting of an outside service. A secret is never sent back, only `configured`."""

    name: str
    label: str
    kind: str
    help: str
    configured: bool
    value: str | None = None
    default: str | None = None
    planned: bool = False


class IntegrationGroup(BaseModel):
    """The values of one outside service."""

    label: str
    items: list[IntegrationItem]


class IntegrationsOverview(BaseModel):
    """Every outside service the portal manages."""

    groups: list[IntegrationGroup]
