import pytest

from app.security.permissions import (
    Principal,
    Reason,
    Resource,
    authorize,
    can_read,
    community_label,
)
from app.security.roles import ROLE_PERMISSIONS, Action, Role, effective_role


def person(role, communities=("c1",), user_id="u1"):
    groups = frozenset({"public"} | {community_label(c) for c in communities})
    return Principal(
        user_id=user_id,
        groups=groups,
        policy_version="v1",
        role=role,
        communities=frozenset(communities),
    )


def test_every_action_has_a_role_rule():
    assert set(ROLE_PERMISSIONS) == set(Action)


@pytest.mark.parametrize(
    ("role", "action", "allowed"),
    [
        (Role.MEMBER, Action.QUERY_ASK, True),
        (Role.MEMBER, Action.REVIEW_APPROVE, False),
        (Role.MEMBER, Action.USER_MANAGE, False),
        (Role.REVIEWER, Action.REVIEW_APPROVE, True),
        (Role.REVIEWER, Action.USER_MANAGE, False),
        (Role.ADMIN, Action.USER_MANAGE, True),
        (Role.ADMIN, Action.RECORDING_REVOKE, True),
        (Role.ADMIN, Action.REVIEW_APPROVE, False),
        (Role.ADMIN, Action.RECORDING_UPLOAD, False),
    ],
)
def test_role_table(role, action, allowed):
    decision = authorize(person(role), action, Resource(community_id="c1", owner_id="other"))
    assert decision.allowed is allowed


def test_other_community_is_denied_even_for_a_reviewer():
    decision = authorize(person(Role.REVIEWER), Action.REVIEW_APPROVE, Resource("c2", "other"))
    assert (decision.allowed, decision.reason) == (False, Reason.COMMUNITY)


def test_admin_has_no_content_access_without_membership():
    decision = authorize(person(Role.ADMIN, communities=()), Action.QUERY_ASK, Resource("c1"))
    assert decision.reason == Reason.COMMUNITY


def test_admin_actions_do_not_need_a_community():
    assert authorize(person(Role.ADMIN, communities=()), Action.USER_MANAGE).allowed


def test_reviewer_cannot_approve_their_own_upload():
    me = person(Role.REVIEWER, user_id="rev")
    decision = authorize(me, Action.REVIEW_APPROVE, Resource("c1", owner_id="rev"))
    assert decision.reason == Reason.SELF_APPROVAL
    assert authorize(me, Action.REVIEW_APPROVE, Resource("c1", owner_id="someone")).allowed


def test_members_edit_only_their_own_drafts_but_reviewers_edit_any():
    member, reviewer = person(Role.MEMBER, user_id="m"), person(Role.REVIEWER, user_id="r")
    assert authorize(member, Action.DRAFT_EDIT, Resource("c1", "m")).allowed
    assert authorize(member, Action.DRAFT_EDIT, Resource("c1", "x")).reason == Reason.NOT_OWNER
    assert authorize(reviewer, Action.DRAFT_EDIT, Resource("c1", "x")).allowed


def test_missing_resource_context_is_denied_for_community_actions():
    assert not authorize(person(Role.MEMBER), Action.MEDIA_PLAY).allowed


def test_asking_a_question_needs_at_least_one_community():
    assert authorize(person(Role.MEMBER), Action.QUERY_ASK).allowed
    assert not authorize(person(Role.MEMBER, communities=()), Action.QUERY_ASK).allowed


@pytest.mark.parametrize(
    ("groups", "stored", "expected"),
    [
        ({"member"}, Role.MEMBER, Role.MEMBER),
        ({"reviewer"}, Role.MEMBER, Role.MEMBER),
        ({"member"}, Role.REVIEWER, Role.MEMBER),
        ({"reviewer"}, Role.REVIEWER, Role.REVIEWER),
        ({"member", "admin"}, Role.ADMIN, Role.ADMIN),
        ({"unknown"}, Role.ADMIN, None),
        (set(), Role.ADMIN, None),
    ],
)
def test_effective_role_needs_both_token_and_database(groups, stored, expected):
    assert effective_role(frozenset(groups), stored) == expected


def test_community_labels_gate_evidence_visibility(evidence):
    mine = evidence.model_copy(update={"access_groups": frozenset({community_label("c1")})})
    other = evidence.model_copy(update={"access_groups": frozenset({community_label("c2")})})
    odd = evidence.model_copy(update={"access_groups": frozenset({"mystery"})})
    me = person(Role.MEMBER)
    assert can_read(me, mine)
    assert not can_read(me, other)
    assert not can_read(me, odd)
