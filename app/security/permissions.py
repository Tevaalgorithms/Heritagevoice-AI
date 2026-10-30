"""Default-deny policy: source visibility (`can_read`) and action authorization (`authorize`)."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.evidence import Evidence
from app.security.roles import (
    ANY_COMMUNITY,
    COMMUNITY_SCOPED,
    OWNED_ONLY,
    ROLE_PERMISSIONS,
    Action,
    Role,
)


class Principal(BaseModel):
    """Built on the server from a verified token plus database records; never from client input."""

    model_config = ConfigDict(frozen=True)
    user_id: str
    groups: frozenset[str]
    policy_version: str
    role: Role = Role.MEMBER
    communities: frozenset[str] = frozenset()


KNOWN_GROUPS = frozenset({"public", "researcher"})
COMMUNITY_PREFIX = "community:"


def community_label(community_id: str) -> str:
    return f"{COMMUNITY_PREFIX}{community_id}"


def is_known_label(label: str) -> bool:
    return label in KNOWN_GROUPS or label.startswith(COMMUNITY_PREFIX)


def can_read(principal: Principal, evidence: Evidence) -> bool:
    labels = evidence.access_groups
    return bool(labels) and all(map(is_known_label, labels)) and bool(labels & principal.groups)


def require_permitted(principal: Principal, items: list[Evidence]) -> list[Evidence]:
    if any(not can_read(principal, item) for item in items):
        raise PermissionError("Evidence failed authorization")
    return items


class Reason(StrEnum):
    """Why an access decision was made."""

    ALLOWED = "allowed"
    ROLE = "role_not_permitted"
    COMMUNITY = "not_a_community_member"
    SELF_APPROVAL = "cannot_approve_own_upload"
    NOT_OWNER = "not_the_owner"


class Decision(BaseModel):
    """The outcome of an access check: allowed or not, and why."""

    model_config = ConfigDict(frozen=True)
    allowed: bool
    reason: Reason


@dataclass(frozen=True)
class Resource:
    """What the action targets. Both fields come from our database, never from the request."""

    community_id: str | None = None
    owner_id: str | None = None


Rule = Callable[[Principal, Action, Resource], Reason | None]


def _role_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    return None if principal.role in ROLE_PERMISSIONS[action] else Reason.ROLE


def _community_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    if action in ANY_COMMUNITY:
        return None if principal.communities else Reason.COMMUNITY
    if action not in COMMUNITY_SCOPED:
        return None
    return None if resource.community_id in principal.communities else Reason.COMMUNITY


def _self_approval_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    own = resource.owner_id == principal.user_id
    return Reason.SELF_APPROVAL if action is Action.REVIEW_APPROVE and own else None


def _ownership_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    own_only = action in OWNED_ONLY and principal.role is Role.MEMBER
    return Reason.NOT_OWNER if own_only and resource.owner_id != principal.user_id else None


RULES: tuple[Rule, ...] = (_role_rule, _community_rule, _self_approval_rule, _ownership_rule)


def authorize(principal: Principal, action: Action, resource: Resource | None = None) -> Decision:
    target = resource or Resource()
    for rule in RULES:
        denial = rule(principal, action, target)
        if denial is not None:
            return Decision(allowed=False, reason=denial)
    return Decision(allowed=True, reason=Reason.ALLOWED)
