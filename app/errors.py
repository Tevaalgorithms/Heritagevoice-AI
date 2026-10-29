"""Errors adapters raise so graphs can turn them into explicit failed states."""


class ProviderError(RuntimeError):
    """An external provider (ASR, LLM, index) failed or timed out.

    `code` is a short, safe label shown to users; the message never leaves the server.
    """

    def __init__(self, message: str = "provider error", code: str = "provider") -> None:
        super().__init__(message)
        self.code = code
