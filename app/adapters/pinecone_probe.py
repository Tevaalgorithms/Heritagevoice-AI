"""The Test button for Pinecone: look up the index with the saved key, without writing anything.

It only asks Pinecone to describe the index, which checks the key, that the index exists, and that
its dimension matches the embedding dimension. Returns a short safe code; provider text and the key
never leave.
"""

from typing import cast

from pinecone import Pinecone
from pydantic import SecretStr

from app.models.llm import ProbeResult

ERROR_CODES = {
    "UnauthorizedException": "bad_key",
    "ForbiddenException": "bad_key",
    "NotFoundException": "unknown_index",
}


def _code_for(error: Exception) -> str:
    return ERROR_CODES.get(type(error).__name__, "provider_error")


def _missing(api_key: SecretStr | None, index: str | None) -> ProbeResult | None:
    if api_key is None:
        return ProbeResult(ok=False, code="no_key")
    return None if index else ProbeResult(ok=False, code="no_index")


def _described(api_key: SecretStr, index: str, dimension: int) -> ProbeResult:
    try:
        described = Pinecone(api_key=api_key.get_secret_value()).describe_index(index)
    except Exception as error:  # report only a short code, never provider text
        return ProbeResult(ok=False, code=_code_for(error))
    matches = getattr(described, "dimension", dimension) == dimension
    return ProbeResult(ok=True) if matches else ProbeResult(ok=False, code="dimension_mismatch")


class PineconeConnection:
    """Checks a Pinecone key and index."""

    def check(self, api_key: SecretStr | None, index: str | None, dimension: int) -> ProbeResult:
        problem = _missing(api_key, index)
        return problem or _described(cast(SecretStr, api_key), cast(str, index), dimension)
