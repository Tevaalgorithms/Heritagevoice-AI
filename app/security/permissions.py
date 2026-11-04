"""Default-deny policy: source visibility (`can_read`) and action authorization (`authorize`)."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.evidence import Evidence
from app.models.groups import OPEN_COMMUNITY
from app.security.roles import (
    ADMIN_ACROSS_COMMUNITIES,
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
    self_review: bool = False  # set only by deployment configuration, never by a request


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


def _exempt_from_membership(principal: Principal, action: Action) -> bool:
    """Actions that do not depend on belonging to the resource's community."""
    admin_wide = principal.role is Role.ADMIN and action in ADMIN_ACROSS_COMMUNITIES
    return admin_wide or action not in COMMUNITY_SCOPED


def _belongs(principal: Principal, resource: Resource) -> bool:
    """A member of the community. In the open-sharing space nobody is a member: you only have
    access to your own recordings there."""
    if resource.community_id == OPEN_COMMUNITY:
        return resource.owner_id == principal.user_id
    return resource.community_id in principal.communities


def _community_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    if _exempt_from_membership(principal, action):
        return None
    return None if _belongs(principal, resource) else Reason.COMMUNITY


def _self_approval_rule(principal: Principal, action: Action, resource: Resource) -> Reason | None:
    own = resource.owner_id == principal.user_id
    forbidden = action is Action.REVIEW_APPROVE and own and not principal.self_review
    return Reason.SELF_APPROVAL if forbidden else None


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
