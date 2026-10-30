"""Typed client for the HeritageVoice API. The token stays on the Streamlit server."""

from http import HTTPStatus

import httpx
from pydantic import BaseModel


class ApiError(Exception):
    """Base class for every failure the UI knows how to explain."""


class ApiNotConfiguredError(ApiError):
    """No API token is configured for this environment."""


class ApiUnavailableError(ApiError):
    """The API could not be reached."""


class ApiNotReadyError(ApiError):
    """The API answered 503: running, but its integrations are not ready."""


class ApiRequestError(ApiError):
    def __init__(self, status_code: int, code: str | None = None) -> None:
        super().__init__(f"The API rejected the request ({status_code})")
        self.status_code = status_code
        self.code = code


class Health(BaseModel):
    status: str
    mode: str


class Readiness(BaseModel):
    ready: bool
    checks: dict[str, str]


class QueryResult(BaseModel):
    status: str
    answer: str = ""
    request_id: str = ""


class UploadSpec(BaseModel):
    data: bytes
    language: str
    community_id: str
    consent_id: str
    heritage_kind: str = "story"


class UploadResult(BaseModel):
    recording_id: str
    job_id: str


class JobView(BaseModel):
    job_id: str
    status: str
    stage: str | None = None
    error: str | None = None
    recording_id: str | None = None


class SegmentView(BaseModel):
    segment_id: str
    start_s: float
    end_s: float
    text: str
    speaker: str | None = None


class VersionView(BaseModel):
    version: int
    status: str
    segments: list[SegmentView]


class RecordingView(BaseModel):
    id: str
    community_id: str
    language: str
    heritage_kind: str = "story"
    status: str
    duration_s: float | None = None
    transcript: VersionView | None = None
    translation: VersionView | None = None


class RecordingSummary(BaseModel):
    id: str
    community_id: str
    language: str
    heritage_kind: str = "story"
    status: str
    duration_s: float | None = None


class ReviewSpec(BaseModel):
    kind: str
    expected_version: int
    approved: bool
    note: str | None = None


class VersionResult(BaseModel):
    kind: str
    version: int
    status: str


class MeView(BaseModel):
    user_id: str
    role: str
    communities: list[str] = []


class ModelParamsSpec(BaseModel):
    provider: str
    model: str
    temperature: float = 0.0
    timeout_s: float = 30.0
    max_retries: int = 2


class ModelView(BaseModel):
    role: str
    provider: str
    model: str
    temperature: float
    timeout_s: float
    max_retries: int
    source: str


class ModelsOverview(BaseModel):
    key_configured: bool
    key_name: str
    allowed: dict[str, list[str]]
    roles: list[ModelView]


class ProbeView(BaseModel):
    ok: bool
    code: str | None = None


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None,
        timeout: float = 50.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._token = token

    def health(self) -> Health:
        return Health.model_validate(self._send("GET", "/health").json())

    def ready(self) -> Readiness:
        """Return the readiness report even when the API answers 503 (not ready)."""
        response = self._send("GET", "/ready", accept_not_ready=True)
        return Readiness.model_validate(response.json())

    def query(self, question: str) -> QueryResult:
        if not self._token:
            raise ApiNotConfiguredError("HERITAGEVOICE_DEV_API_TOKEN is not set")
        response = self._send("POST", "/query", json={"question": question}, auth=True)
        return QueryResult.model_validate(response.json())

    def upload_recording(self, spec: UploadSpec, idempotency_key: str) -> UploadResult:
        """Send the audio under a generic file name; the original name is never uploaded."""
        form = {
            "language": spec.language,
            "community_id": spec.community_id,
            "consent_id": spec.consent_id,
            "heritage_kind": spec.heritage_kind,
        }
        response = self._send(
            "POST",
            "/v1/recordings",
            auth=True,
            data=form,
            files={"file": ("recording", spec.data, "application/octet-stream")},
            headers={"Idempotency-Key": idempotency_key},
        )
        return UploadResult.model_validate(response.json())

    def get_job(self, job_id: str) -> JobView:
        return JobView.model_validate(self._send("GET", f"/v1/jobs/{job_id}", auth=True).json())

    def get_recording(self, recording_id: str) -> RecordingView:
        response = self._send("GET", f"/v1/recordings/{recording_id}", auth=True)
        return RecordingView.model_validate(response.json())

    def list_recordings(self) -> list[RecordingSummary]:
        response = self._send("GET", "/v1/recordings", auth=True)
        return [RecordingSummary.model_validate(item) for item in response.json()]

    def edit_draft(
        self, recording_id: str, kind: str, expected_version: int, edits: dict[str, str]
    ) -> VersionResult:
        body = {
            "kind": kind,
            "expected_version": expected_version,
            "edits": [{"segment_id": sid, "text": text} for sid, text in edits.items()],
        }
        response = self._send("PATCH", f"/v1/recordings/{recording_id}/draft", auth=True, json=body)
        return VersionResult.model_validate(response.json())

    def review(self, recording_id: str, spec: ReviewSpec) -> VersionResult:
        response = self._send(
            "POST", f"/v1/recordings/{recording_id}/review", auth=True, json=spec.model_dump()
        )
        return VersionResult.model_validate(response.json())

    def publish(self, recording_id: str) -> str:
        response = self._send("POST", f"/v1/recordings/{recording_id}/publish", auth=True)
        return str(response.json()["status"])

    def me(self) -> MeView:
        return MeView.model_validate(self._send("GET", "/v1/me", auth=True).json())

    def model_settings(self) -> ModelsOverview:
        return ModelsOverview.model_validate(self._send("GET", "/admin/models", auth=True).json())

    def save_model_setting(self, role: str, params: ModelParamsSpec) -> ModelView:
        response = self._send("PUT", f"/admin/models/{role}", auth=True, json=params.model_dump())
        return ModelView.model_validate(response.json())

    def reset_model_setting(self, role: str) -> ModelView:
        response = self._send("DELETE", f"/admin/models/{role}", auth=True)
        return ModelView.model_validate(response.json())

    def probe_model_setting(self, role: str, params: ModelParamsSpec) -> ProbeView:
        response = self._send(
            "POST", f"/admin/models/{role}/test", auth=True, json=params.model_dump()
        )
        return ProbeView.model_validate(response.json())

    def _send(
        self,
        method: str,
        path: str,
        auth: bool = False,
        accept_not_ready: bool = False,
        **kwargs: object,
    ) -> httpx.Response:
        extra = kwargs.pop("headers", None)
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
        headers.update(extra or {})  # type: ignore[arg-type]
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)  # type: ignore[arg-type]
        except httpx.RequestError as error:
            raise ApiUnavailableError(path) from error
        return _checked(response, accept_not_ready)


def _checked(response: httpx.Response, accept_not_ready: bool) -> httpx.Response:
    if response.is_success:
        return response
    if response.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
        if accept_not_ready:
            return response
        raise ApiNotReadyError(response.url.path)
    raise ApiRequestError(response.status_code, _error_code(response))


def _error_code(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail.get("code") if isinstance(detail, dict) else None
