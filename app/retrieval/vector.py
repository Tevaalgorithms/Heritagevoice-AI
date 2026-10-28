"""Apply authorization filters in the vector query before loading passages."""

from app.config import IntegrationNotConfigured
from app.models.evidence import Evidence
from app.security.permissions import Principal


def search(query: str, principal: Principal, limit: int = 20) -> list[Evidence]:
    raise IntegrationNotConfigured("Embedding/vector index adapter is not implemented")
