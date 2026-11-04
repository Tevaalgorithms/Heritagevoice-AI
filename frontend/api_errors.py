"""The failures the UI knows how to explain. Each one maps to a plain-language message."""


class ApiError(Exception):
    """Base class for every failure the UI knows how to explain."""


class ApiNotConfiguredError(ApiError):
    """No API token is configured for this environment."""


class ApiUnavailableError(ApiError):
    """The API could not be reached."""


class ApiNotReadyError(ApiError):
    """The API answered 503: running, but its integrations are not ready."""


class ApiRequestError(ApiError):
    """The API refused the request; carries the status, a safe code, the request's reference
    (to quote to whoever runs the site) and, for refused values, which fields were wrong."""

    def __init__(
        self,
        status_code: int,
        code: str | None = None,
        reference: str | None = None,
        problems: tuple[str, ...] = (),
    ) -> None:
        super().__init__(f"The API rejected the request ({status_code})")
        self.status_code = status_code
        self.code = code
        self.reference = reference
        self.problems = problems
