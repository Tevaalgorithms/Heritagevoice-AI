import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.recordings import get_audio_store
from app.audio import AudioRules
from app.db.repositories import CommunityRepository, ConsentRepository, RecordingRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.fakes import FakeAudioStore
from app.indexing import IndexDeps, index_one
from app.models.groups import OPEN_COMMUNITY
from app.models.records import RecordingStatus, Right, Visibility
from app.retrieval.search import lexical_evidence
from app.security.permissions import Resource, authorize
from app.security.roles import Action, Role
from app.uploads import UploadDeps, UploadRequest, accept_upload
from tests.helpers import person, wav_bytes
from tests.index_helpers import published

MEMBER = person(Role.MEMBER, user_id="member-1", communities=())
OTHER = person(Role.MEMBER, user_id="member-2", communities=())
COORDINATOR = person(Role.REVIEWER, user_id="coord-1", communities=("my-family",))
ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
OPEN_RIGHTS = {
    Right.AI_PROCESSING,
    Right.TRANSLATION,
    Right.INDEXING,
    Right.SUMMARIZATION,
    Right.PUBLIC_SHARING,
    Right.PLAYBACK,
}
RULES = AudioRules(max_bytes=5_000_000, max_seconds=600.0, languages=frozenset({"ta", "en"}))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'open.db'}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = FakeAudioStore
    app.dependency_overrides[current_principal] = lambda: MEMBER
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(principal):
    app.dependency_overrides[current_principal] = lambda: principal


def give_consent(client, **body):
    return client.post("/v1/open-sharing/consent", json={"confirm": True, **body})


def stored(engine, consent_id):
    with Session(engine) as session:
        return ConsentRepository(session).get(consent_id)


def test_a_member_gives_consent_for_open_sharing_without_any_group(client, engine):
    response = give_consent(client)
    assert response.status_code == 201
    consent = stored(engine, response.json()["consent_id"])
    assert consent.community_id == OPEN_COMMUNITY
    assert {
        Right.AI_PROCESSING,
        Right.TRANSLATION,
        Right.INDEXING,
        Right.SUMMARIZATION,
        Right.PUBLIC_SHARING,
        Right.PLAYBACK,
    } <= consent.rights
    assert Right.ATTRIBUTION not in consent.rights


def test_playback_and_attribution_are_the_only_optional_rights(client, engine):
    chosen = give_consent(client, playback=False, attribution=True).json()["consent_id"]
    rights = stored(engine, chosen).rights
    assert Right.PLAYBACK not in rights
    assert {Right.ATTRIBUTION, Right.PUBLIC_SHARING, Right.AI_PROCESSING} <= rights


@pytest.mark.parametrize("body", [{"confirm": False}, {}, {"confirm": True, "rights": ["x"]}])
def test_without_confirming_the_right_to_share_nothing_is_recorded(client, engine, body):
    assert client.post("/v1/open-sharing/consent", json=body).status_code == 422
    with Session(engine) as session:
        assert session.scalars(select(AuditLogRow)).all() == []


def test_the_consent_is_audited_with_who_gave_it(client, engine):
    consent_id = give_consent(client).json()["consent_id"]
    with Session(engine) as session:
        (entry,) = session.scalars(select(AuditLogRow))
    assert (entry.actor_sub, entry.action, entry.target) == (
        "member-1",
        "consent:open",
        f"consent:{consent_id}",
    )


def upload(engine, principal, consent_id):
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(
        principal,
        OPEN_COMMUNITY,
        "ta",
        consent_id,
        "key-00000001",
        wav_bytes(1.0),
        visibility=Visibility.PUBLIC,
    )
    return accept_upload(request, deps)


def test_a_member_with_no_group_can_upload_openly(client, engine):
    consent_id = give_consent(client).json()["consent_id"]
    accepted = upload(engine, MEMBER, consent_id)
    with Session(engine) as session:
        recording = RecordingRepository(session).get(accepted.recording_id)
    assert (recording.community_id, recording.visibility) == (OPEN_COMMUNITY, Visibility.PUBLIC)


def test_an_open_consent_cannot_be_used_in_a_group(client, engine):
    consent_id = give_consent(client).json()["consent_id"]
    deps = UploadDeps(lambda: session_scope(engine), FakeAudioStore(), RULES)
    request = UploadRequest(
        COORDINATOR, "my-family", "ta", consent_id, "k-00000001", wav_bytes(1.0)
    )
    with pytest.raises(Exception, match="onsent"):
        accept_upload(request, deps)


@pytest.mark.parametrize("principal", [OTHER, COORDINATOR])
def test_nobody_but_the_owner_and_admins_can_see_an_open_draft(principal):
    mine = Resource(OPEN_COMMUNITY, "member-1")
    assert authorize(MEMBER, Action.RECORDING_VIEW, mine).allowed
    assert not authorize(principal, Action.RECORDING_VIEW, mine).allowed
    assert not authorize(principal, Action.MEDIA_PLAY, mine).allowed
    assert not authorize(principal, Action.DRAFT_EDIT, mine).allowed
    assert authorize(ADMIN, Action.RECORDING_VIEW, mine).allowed


def test_a_member_lists_their_own_open_uploads_but_a_coordinator_does_not_see_others(
    client, engine
):
    consent_id = give_consent(client).json()["consent_id"]
    accepted = upload(engine, MEMBER, consent_id)
    assert [r["id"] for r in client.get("/v1/recordings").json()] == [accepted.recording_id]
    act_as(COORDINATOR)
    assert client.get("/v1/recordings").json() == []
    act_as(OTHER)
    assert client.get("/v1/recordings").json() == []


def test_the_open_space_is_reserved_and_never_listed_as_a_group(client, engine):
    with session_scope(engine) as session:
        repo = CommunityRepository(session)
        group = repo.create("Everyone", "admin-1")
    assert group.id != OPEN_COMMUNITY
    act_as(ADMIN)
    assert OPEN_COMMUNITY not in [g["id"] for g in client.get("/admin/groups").json()]


def test_a_published_open_recording_is_found_by_anyone_but_a_draft_is_not(engine):
    stranger = person(Role.MEMBER, user_id="stranger", communities=())
    with session_scope(engine) as session:
        published(
            session,
            community=OPEN_COMMUNITY,
            visibility=Visibility.PUBLIC,
            consent={"rights": tuple(OPEN_RIGHTS)},
        )
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")
    with Session(engine) as session:
        assert len(lexical_evidence(session, stranger, "water", 20)) >= 1
    with session_scope(engine) as session:
        RecordingRepository(session).set_status("r1", RecordingStatus.REVIEW)
    with Session(engine) as session:
        assert lexical_evidence(session, stranger, "water", 20) == []
