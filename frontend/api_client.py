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
    def __init__(self, status_code: int) -> None:
        super().__init__(f"The API rejected the request ({status_code})")
        self.status_code = status_code


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

    def _send(
        self,
        method: str,
        path: str,
        auth: bool = False,
        accept_not_ready: bool = False,
        **kwargs: object,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._token}"} if auth else {}
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
    raise ApiRequestError(response.status_code)
