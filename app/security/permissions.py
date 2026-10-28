"""Default-deny source policy. Real identity/ownership integration is pending."""

from pydantic import BaseModel, ConfigDict

from app.models.evidence import Evidence


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    groups: frozenset[str]
    policy_version: str


KNOWN_GROUPS = frozenset({"public", "researcher"})


def can_read(principal: Principal, evidence: Evidence) -> bool:
    labels = evidence.access_groups
    return bool(labels) and labels <= KNOWN_GROUPS and bool(labels & principal.groups)


def require_permitted(principal: Principal, items: list[Evidence]) -> list[Evidence]:
    if any(not can_read(principal, item) for item in items):
        raise PermissionError("Evidence failed authorization")
    return items
