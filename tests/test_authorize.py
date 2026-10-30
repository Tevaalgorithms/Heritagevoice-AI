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
        (Role.REVIEWER, Action.REVIEW_APPROVE, False),
        (Role.REVIEWER, Action.USER_MANAGE, False),
        (Role.MEMBER, Action.LIBRARY_VIEW, True),
        (Role.MEMBER, Action.VISIBILITY_MANAGE, False),
        (Role.REVIEWER, Action.VISIBILITY_MANAGE, False),
        (Role.ADMIN, Action.VISIBILITY_MANAGE, True),
        (Role.ADMIN, Action.LIBRARY_VIEW, True),
        (Role.ADMIN, Action.INTEGRATION_MANAGE, True),
        (Role.MEMBER, Action.INTEGRATION_MANAGE, False),
        (Role.REVIEWER, Action.INTEGRATION_MANAGE, False),
        (Role.ADMIN, Action.USER_MANAGE, True),
        (Role.ADMIN, Action.RECORDING_REVOKE, True),
        (Role.ADMIN, Action.REVIEW_APPROVE, True),
        (Role.ADMIN, Action.RECORDING_UPLOAD, True),
    ],
)
def test_role_table(role, action, allowed):
    decision = authorize(person(role), action, Resource(community_id="c1", owner_id="other"))
    assert decision.allowed is allowed


def test_an_admin_may_approve_in_any_community_but_only_members_of_it_may_upload():
    admin = person(Role.ADMIN, communities=())
    assert authorize(admin, Action.REVIEW_APPROVE, Resource("c2", "other")).allowed
    denied = authorize(admin, Action.RECORDING_UPLOAD, Resource("c2", admin.user_id))
    assert (denied.allowed, denied.reason) == (False, Reason.COMMUNITY)


def test_the_old_reviewer_role_is_denied_approval_everywhere():
    decision = authorize(person(Role.REVIEWER), Action.REVIEW_APPROVE, Resource("c1", "other"))
    assert (decision.allowed, decision.reason) == (False, Reason.ROLE)


def test_admin_has_no_content_access_without_membership():
    decision = authorize(person(Role.ADMIN, communities=()), Action.QUERY_ASK, Resource("c1"))
    assert decision.reason == Reason.COMMUNITY


def test_admin_actions_do_not_need_a_community():
    assert authorize(person(Role.ADMIN, communities=()), Action.USER_MANAGE).allowed


def test_an_admin_cannot_approve_their_own_upload_unless_the_deployment_allows_it():
    me = person(Role.ADMIN, user_id="boss")
    decision = authorize(me, Action.REVIEW_APPROVE, Resource("c1", owner_id="boss"))
    assert decision.reason == Reason.SELF_APPROVAL
    assert authorize(me, Action.REVIEW_APPROVE, Resource("c1", owner_id="someone")).allowed
    solo = me.model_copy(update={"self_review": True})
    assert authorize(solo, Action.REVIEW_APPROVE, Resource("c1", owner_id="boss")).allowed


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
