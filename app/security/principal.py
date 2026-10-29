"""Build the server-side Principal. Inputs are a verified token and our own database only."""

from collections.abc import Iterable

from app.config import Settings
from app.models.users import StoredUser, UserStatus
from app.security.permissions import Principal, community_label
from app.security.roles import effective_role

POLICY_VERSION = "v1"
DEV_COMMUNITY = "dev"


def _groups(communities: Iterable[str]) -> frozenset[str]:
    return frozenset({"public"} | {community_label(c) for c in communities})


def build_principal(user: StoredUser | None, token_groups: frozenset[str]) -> Principal | None:
    """None means deny: unknown user, disabled user, or no role both token and database agree on."""
    if user is None or user.status is not UserStatus.ACTIVE:
        return None
    role = effective_role(token_groups, user.role)
    if role is None:
        return None
    return Principal(
        user_id=user.sub,
        groups=_groups(user.communities),
        policy_version=POLICY_VERSION,
        role=role,
        communities=user.communities,
    )


def dev_principal(settings: Settings) -> Principal:
    """Local development only; `current_principal` refuses this outside the local environment."""
    return Principal(
        user_id="dev-user",
        groups=_groups({DEV_COMMUNITY}),
        policy_version=POLICY_VERSION,
        role=settings.dev_role,
        communities=frozenset({DEV_COMMUNITY}),
    )
