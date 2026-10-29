"""Index only the principal's authorized chunks before calling this adapter."""

from app.config import IntegrationNotConfiguredError
from app.models.evidence import Evidence


def search(query: str, authorized_corpus: list[Evidence], limit: int = 20) -> list[Evidence]:
    raise IntegrationNotConfiguredError("BM25 index/tokenizer is not implemented")
