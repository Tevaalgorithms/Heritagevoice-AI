"""Typed client for the HeritageVoice API. The token stays on the Streamlit server.

The error types and data shapes live in `frontend.api_errors` and `frontend.api_models`; they are
re-exported here so callers can keep importing everything from `frontend.api_client`.
"""

from http import HTTPStatus

import httpx

from frontend.api_errors import (
    ApiError,
    ApiNotConfiguredError,
    ApiNotReadyError,
    ApiRequestError,
    ApiUnavailableError,
)
from frontend.api_models import (
    CatalogView,
    CitationView,
    Health,
    IntegrationGroup,
    IntegrationItem,
    IntegrationsOverview,
    JobView,
    LibraryItem,
    LibraryResult,
    LibrarySpec,
    MeView,
    ModelParamsSpec,
    ModelsOverview,
    ModelView,
    NewModelSpec,
    ProbeView,
    QueryResult,
    Readiness,
    RecordingSummary,
    RecordingView,
    ReviewSpec,
    SegmentView,
    SignupView,
    UploadResult,
    UploadSpec,
    VersionResult,
    VersionView,
    VisibilityResult,
)

__all__ = [
    "ApiClient",
    "IntegrationGroup",
    "IntegrationItem",
    "IntegrationsOverview",
    "CitationView",
    "LibraryItem",
    "LibraryResult",
    "LibrarySpec",
    "VisibilityResult",
    "ApiError",
    "ApiNotConfiguredError",
    "ApiNotReadyError",
    "ApiRequestError",
    "ApiUnavailableError",
    "CatalogView",
    "Health",
    "JobView",
    "MeView",
    "ModelParamsSpec",
    "ModelView",
    "ModelsOverview",
    "NewModelSpec",
    "ProbeView",
    "QueryResult",
    "Readiness",
    "RecordingSummary",
    "RecordingView",
    "ReviewSpec",
    "SegmentView",
    "SignupView",
    "UploadResult",
    "UploadSpec",
    "VersionResult",
    "VersionView",
]


class ApiClient:
    """Calls the HeritageVoice API on behalf of the signed-in user."""

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
        response = self._send("POST", "/v1/query", json={"question": question}, auth=True)
        return QueryResult.model_validate(response.json())

    def upload_recording(self, spec: UploadSpec, idempotency_key: str) -> UploadResult:
        """Send the audio under a generic file name; the original name is never uploaded."""
        form = {
            "language": spec.language,
            "community_id": spec.community_id,
            "consent_id": spec.consent_id,
            "heritage_kind": spec.heritage_kind,
            "visibility": spec.visibility,
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

    def library(self, spec: LibrarySpec) -> LibraryResult:
        """Browse, or search when `q` is set. Empty filters are not sent."""
        params = {k: v for k, v in spec.model_dump().items() if v not in ("", None)}
        response = self._send("GET", "/v1/library", auth=True, params=params)
        return LibraryResult.model_validate(response.json())

    def public_library(self, spec: LibrarySpec) -> LibraryResult:
        """Search the public recordings. Needs no sign-in, so no token is sent."""
        params = {k: v for k, v in spec.model_dump().items() if v not in ("", None)}
        response = self._send("GET", "/v1/public/library", auth=False, params=params)
        return LibraryResult.model_validate(response.json())

    def set_visibility(self, recording_id: str, visibility: str) -> VisibilityResult:
        response = self._send(
            "PUT",
            f"/v1/recordings/{recording_id}/visibility",
            auth=True,
            json={"visibility": visibility},
        )
        return VisibilityResult.model_validate(response.json())

    def publish(self, recording_id: str) -> str:
        response = self._send("POST", f"/v1/recordings/{recording_id}/publish", auth=True)
        return str(response.json()["status"])

    def me(self) -> MeView:
        return MeView.model_validate(self._send("GET", "/v1/me", auth=True).json())

    def signups(self) -> list[SignupView]:
        """People who created an account and wait for approval (admins only)."""
        response = self._send("GET", "/admin/signups", auth=True)
        return [SignupView.model_validate(item) for item in response.json()]

    def approve_signup(self, sub: str, communities: list[str]) -> None:
        self._send(
            "POST", f"/admin/signups/{sub}/approve", auth=True, json={"communities": communities}
        )

    def decline_signup(self, sub: str) -> None:
        self._send("POST", f"/admin/signups/{sub}/decline", auth=True)

    def invite_user(self, email: str, role: str, communities: list[str]) -> None:
        """Invite a person by email with a role. This is the only way an admin is created."""
        body = {"email": email, "role": role, "communities": communities}
        self._send("POST", "/admin/users", auth=True, json=body)

    def model_settings(self) -> ModelsOverview:
        return ModelsOverview.model_validate(self._send("GET", "/admin/models", auth=True).json())

    def add_model(self, spec: NewModelSpec) -> CatalogView:
        response = self._send("POST", "/admin/models/catalog", auth=True, json=spec.model_dump())
        return CatalogView.model_validate(response.json())

    def integrations(self) -> IntegrationsOverview:
        response = self._send("GET", "/admin/integrations", auth=True)
        return IntegrationsOverview.model_validate(response.json())

    def save_integration(self, name: str, value: str) -> IntegrationItem:
        """Send a key or setting once. The server stores it and never returns a secret."""
        response = self._send(
            "PUT", f"/admin/integrations/{name}", auth=True, json={"value": value}
        )
        return IntegrationItem.model_validate(response.json())

    def test_pinecone(self) -> ProbeView:
        response = self._send("POST", "/admin/integrations/pinecone/test", auth=True)
        return ProbeView.model_validate(response.json())

    def set_model_status(self, model_id: str, status: str) -> CatalogView:
        response = self._send(
            "PUT", f"/admin/models/catalog/{model_id}", auth=True, json={"status": status}
        )
        return CatalogView.model_validate(response.json())

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
