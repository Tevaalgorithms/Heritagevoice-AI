"""Roles and the action table. Cognito proves who a user is; this table decides what they can do."""

from enum import IntEnum, StrEnum


class Role(StrEnum):
    """A user's role. People see `reviewer` as Coordinator: it manages groups and consents."""

    MEMBER = "member"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Action(StrEnum):
    """Something a user can try to do; each is allowed for certain roles."""

    RECORDING_UPLOAD = "recording:upload"
    RECORDING_VIEW = "recording:view"
    QUERY_ASK = "query:ask"
    MEDIA_PLAY = "media:play"
    DRAFT_EDIT = "draft:edit"
    REVIEW_APPROVE = "review:approve"
    LIBRARY_VIEW = "library:view"
    VISIBILITY_MANAGE = "visibility:manage"
    INTEGRATION_MANAGE = "integration:manage"
    RECORDING_REVOKE = "recording:revoke"
    CONSENT_MANAGE = "consent:manage"
    GROUP_MANAGE = "group:manage"
    MODEL_MANAGE = "model:manage"
    USER_MANAGE = "user:manage"
    INDEX_REBUILD = "index:rebuild"


class Rank(IntEnum):
    """Orders roles so the lower of two can be taken."""

    MEMBER = 1
    REVIEWER = 2
    ADMIN = 3


ROLE_PERMISSIONS: dict[Action, frozenset[Role]] = {
    Action.RECORDING_UPLOAD: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    Action.RECORDING_VIEW: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    Action.QUERY_ASK: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    Action.MEDIA_PLAY: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    Action.DRAFT_EDIT: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    # Only admins review. The reviewer role stays for compatibility but carries no review right.
    Action.REVIEW_APPROVE: frozenset({Role.ADMIN}),
    Action.LIBRARY_VIEW: frozenset({Role.MEMBER, Role.REVIEWER, Role.ADMIN}),
    Action.VISIBILITY_MANAGE: frozenset({Role.ADMIN}),
    Action.INTEGRATION_MANAGE: frozenset({Role.ADMIN}),
    Action.RECORDING_REVOKE: frozenset({Role.ADMIN}),
    # Coordinators (the reviewer role) manage groups and consents, only for groups they belong to.
    Action.CONSENT_MANAGE: frozenset({Role.REVIEWER, Role.ADMIN}),
    Action.GROUP_MANAGE: frozenset({Role.REVIEWER, Role.ADMIN}),
    Action.MODEL_MANAGE: frozenset({Role.ADMIN}),
    Action.USER_MANAGE: frozenset({Role.ADMIN}),
    Action.INDEX_REBUILD: frozenset({Role.ADMIN}),
}
# Actions that touch community content and so need community membership (admin actions do not).
COMMUNITY_SCOPED = frozenset(
    {
        Action.RECORDING_UPLOAD,
        Action.RECORDING_VIEW,
        Action.MEDIA_PLAY,
        Action.DRAFT_EDIT,
        Action.REVIEW_APPROVE,
    }
)
# Admins review and edit across every community, so these actions need no membership for them.
ADMIN_ACROSS_COMMUNITIES = frozenset(
    {Action.RECORDING_VIEW, Action.DRAFT_EDIT, Action.REVIEW_APPROVE, Action.MEDIA_PLAY}
)
# Members act only on their own items; reviewers act across their communities.
OWNED_ONLY = frozenset({Action.DRAFT_EDIT, Action.RECORDING_VIEW})


def rank(role: Role) -> int:
    return Rank[role.name]


def effective_role(token_groups: frozenset[str], stored_role: Role) -> Role | None:
    """The role both the signed token and the database agree on; the lower one wins.

    A token that names no known group yields no role at all, so the caller denies the request.
    """
    claimed = [Role(g) for g in token_groups if g in Role._value2member_map_]
    if not claimed:
        return None
    return min(stored_role, max(claimed, key=rank), key=rank)
