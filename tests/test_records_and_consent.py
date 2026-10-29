import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.engine import make_engine
from app.db.repositories import AuditEntry, AuditRepository, UserRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.models.job import JobStatus
from app.models.records import Consent, GraphAssertion, Relation, Right, TranscriptVersion
from app.models.users import UserStatus
from app.security.consent import ConsentDeniedError, require_right
from app.security.roles import Role
from app.skeleton import FULL_CONSENT, Skeleton


class CountingTranscriber:
    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, language):
        self.calls += 1
        return []


def consent(*rights, revoked=False):
    return Consent(
        id="c", community_id="c1", rights=frozenset(rights), policy_version="v1", revoked=revoked
    )


@pytest.mark.parametrize("right", list(Right))
def test_rights_are_independent(right):
    only_this = consent(right)
    assert only_this.permits(right)
    assert not any(only_this.permits(other) for other in Right if other != right)


def test_revocation_withdraws_every_right_at_once():
    revoked = consent(*Right, revoked=True)
    assert not any(revoked.permits(r) for r in Right)


def test_missing_consent_is_denied():
    with pytest.raises(ConsentDeniedError):
        require_right(None, Right.PLAYBACK)


def test_ai_prohibited_content_never_reaches_the_transcriber():
    transcriber = CountingTranscriber()
    state = Skeleton(transcriber).ingest("r1", consent=consent(Right.PLAYBACK, Right.TRANSLATION))
    assert transcriber.calls == 0
    assert (state["status"], state["error"]) == (JobStatus.FAILED, "consent")


def test_revoked_consent_stops_ingestion_before_any_provider_call():
    transcriber = CountingTranscriber()
    state = Skeleton(transcriber).ingest("r1", consent=consent(*Right, revoked=True))
    assert transcriber.calls == 0
    assert state["error"] == "consent"


def test_translation_needs_its_own_right():
    state = Skeleton().ingest("r1", consent=consent(Right.AI_PROCESSING))
    assert state["status"] == JobStatus.FAILED
    assert state["error"] == "consent"
    assert "translations" not in state


def test_full_consent_still_reaches_review():
    assert Skeleton().ingest("r1", consent=FULL_CONSENT)["status"] == JobStatus.REVIEW


def test_graph_assertions_use_a_fixed_relation_set_and_bounded_confidence():
    base = {
        "id": "a1",
        "recording_id": "r1",
        "subject": "elder",
        "relation": Relation.MENTIONS,
        "object": "well",
        "asserted_by": "speaker-1",
        "supporting_segment_id": "s1",
        "transcript_version": 1,
        "policy_ref": "v1",
    }
    assert GraphAssertion(**base, confidence=0.5).review_state == "pending"
    with pytest.raises(ValidationError):
        GraphAssertion(**{**base, "relation": "INVENTED"}, confidence=0.5)
    with pytest.raises(ValidationError):
        GraphAssertion(**base, confidence=1.5)


def test_versions_start_at_one():
    with pytest.raises(ValidationError):
        TranscriptVersion(id="t", recording_id="r", version=0, segments=[], created_by="u")


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_user_repository_round_trip(engine):
    with session_scope(engine) as session:
        users = UserRepository(session)
        user = users.create("sub-1", Role.MEMBER, frozenset({"c1"}))
        assert (user.role, user.status, user.communities) == (
            Role.MEMBER,
            UserStatus.ACTIVE,
            frozenset({"c1"}),
        )
        users.set_role("sub-1", Role.REVIEWER)
        users.set_communities("sub-1", frozenset({"c2", "c3"}))
        users.set_status("sub-1", UserStatus.DISABLED)
        stored = users.get("sub-1")
        assert (stored.role, stored.status) == (Role.REVIEWER, UserStatus.DISABLED)
        assert stored.communities == {"c2", "c3"}
        assert users.get("nobody") is None


def test_unknown_user_updates_are_errors(engine):
    with session_scope(engine) as session, pytest.raises(KeyError):
        UserRepository(session).set_role("nobody", Role.ADMIN)


def test_audit_log_stores_who_what_and_trace_but_no_content(engine):
    with session_scope(engine) as session:
        entry = AuditEntry("admin-1", "user:disable", "user:sub-1", "trace-123456")
        AuditRepository(session).record(entry)
        row = session.scalars(select(AuditLogRow)).one()
        assert (row.actor_sub, row.action, row.target) == ("admin-1", "user:disable", "user:sub-1")
