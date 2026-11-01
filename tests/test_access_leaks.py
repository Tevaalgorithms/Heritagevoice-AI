"""Access-leak matrix: for every state a recording can be in, who can find it, ask about it and
play it. A recording is indexed first and its state is changed afterwards, so each case also proves
that a stale search result can never get past the live checks. Zero leaks is the pass mark.

Readers: a `member` of the recording's community, an `outsider` (signed in, another community) and
a `visitor` (no account). A visitor cannot ask questions, so only the first two ask.
"""

import contextlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.agents.answer_agent import AnswerAgent, AnswerDraft
from app.agents.hybrid_rag import HybridRetriever
from app.agents.supervisor import RouteDecision, Supervisor
from app.agents.verifier import ClaimCheck, Verification, Verifier
from app.api.auth import current_principal, get_session_factory
from app.api.main import app
from app.api.public import get_limiter, get_media_limiter
from app.api.query import get_agents
from app.api.recordings import get_audio_store
from app.db.repositories import ConsentRepository
from app.db.session import session_scope
from app.db.tables import Base, RecordingRow
from app.fakes import FakeAudioStore
from app.graph.workflow import Agents
from app.indexing import IndexDeps, IndexRefusedError, index_one
from app.models.evidence import Route
from app.models.records import RecordingStatus, Right, Visibility
from app.ratelimit import SlidingWindowLimiter
from app.revocation import revoke_recording
from tests.helpers import person, wav_bytes
from tests.index_helpers import published
from tests.qa_helpers import Script, no_graph

AUDIO = wav_bytes(1.0)
MEMBER, OUTSIDER, VISITOR = "member", "outsider", "visitor"
EVERYONE = {MEMBER, OUTSIDER, VISITOR}
WITHOUT = {r: [x for x in Right if x is not r] for r in Right}


def _withdraw(session):
    ConsentRepository(session).revoke("consent-1")


def _take_down(session):
    revoke_recording(session, "r1")


def _back_to_review(session):
    session.get(RecordingRow, "r1").status = RecordingStatus.REVIEW


def _nothing(session):
    return None


# state -> (how the recording is built, what changes after indexing,
#           who can find it, who can play it)
CASES = {
    "community only": (dict(visibility=Visibility.COMMUNITY), _nothing, {MEMBER}, {MEMBER}),
    "shared publicly": (dict(visibility=Visibility.PUBLIC), _nothing, EVERYONE, EVERYONE),
    "public, but consent lacks public sharing": (
        dict(visibility=Visibility.PUBLIC, consent={"rights": WITHOUT[Right.PUBLIC_SHARING]}),
        _nothing,
        {MEMBER},
        {MEMBER},
    ),
    "public, but consent lacks playback": (
        dict(visibility=Visibility.PUBLIC, consent={"rights": WITHOUT[Right.PLAYBACK]}),
        _nothing,
        EVERYONE,
        set(),
    ),
    "consent forbids indexing and AI processing": (
        dict(
            visibility=Visibility.PUBLIC,
            consent={"rights": [Right.PLAYBACK, Right.PUBLIC_SHARING]},
        ),
        _nothing,
        set(),
        EVERYONE,
    ),
    "sent back to review after it was indexed": (
        dict(visibility=Visibility.PUBLIC),
        _back_to_review,
        set(),
        set(),
    ),
    "consent withdrawn after it was indexed": (
        dict(visibility=Visibility.PUBLIC),
        _withdraw,
        set(),
        set(),
    ),
    "taken down after it was indexed": (
        dict(visibility=Visibility.PUBLIC),
        _take_down,
        set(),
        set(),
    ),
}


@pytest.fixture
def world(tmp_path):
    """A database, an audio store and the API wired to them, with no one signed in."""
    engine = create_engine(f"sqlite:///{tmp_path / 'leaks.db'}")
    Base.metadata.create_all(engine)
    store = FakeAudioStore()
    generous = SlidingWindowLimiter(10_000, 60.0)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[get_audio_store] = lambda: store
    app.dependency_overrides[get_limiter] = lambda: generous
    app.dependency_overrides[get_media_limiter] = lambda: generous
    app.dependency_overrides[get_agents] = lambda: _agents(engine)
    yield engine, store
    app.dependency_overrides.clear()


def _agents(engine):
    claim = ClaimCheck(text="Water was shared.", passages=["p1"])
    return Agents(
        classify=Supervisor(Script(RouteDecision(route=Route.HYBRID))),
        hybrid=HybridRetriever(lambda: session_scope(engine)),
        graph=no_graph,
        verify=Verifier(Script(Verification(claims=[claim], coverage="full"))),
        answer=AnswerAgent(Script(AnswerDraft(answer="Water was shared [1].", claims_used=[1]))),
    )


def build(world, state):
    engine, store = world
    options, change, _, _ = CASES[state]
    with session_scope(engine) as session:
        published(session, "r1", "c1", **options)
        session.get(RecordingRow, "r1").audio_key = "audio/r1"
    store.put("audio/r1", AUDIO, "audio/wav")
    with contextlib.suppress(IndexRefusedError):  # a consent that forbids indexing is refused
        index_one(IndexDeps(lambda: session_scope(engine)), "r1")
    with session_scope(engine) as session:
        change(session)


def as_reader(reader):
    communities = ("c1",) if reader == MEMBER else ("c9",)
    app.dependency_overrides[current_principal] = lambda: person(
        user_id=f"{reader}-1", communities=communities
    )
    return TestClient(app)


def library_ids(reader):
    """Recordings the reader finds, by browsing and by searching in both languages."""
    found = set()
    for params in ({}, {"q": "water", "view": "translation"}, {"q": "தண்ணீர்"}):
        url = "/v1/public/library" if reader == VISITOR else "/v1/library"
        body = as_reader(reader).get(url, params=params).json()
        found |= {item["recording_id"] for item in body["items"]}
    return found


def asked_ids(reader):
    body = as_reader(reader).post("/v1/query", json={"question": "shared the water"}).json()
    return {c["recording_id"] for c in body["citations"]}


def plays(reader):
    url = "/v1/public/recordings/r1/media" if reader == VISITOR else "/v1/recordings/r1/media"
    return as_reader(reader).get(url).status_code == 200


@pytest.mark.parametrize("state", CASES)
@pytest.mark.parametrize("reader", [MEMBER, OUTSIDER, VISITOR])
def test_only_the_right_readers_can_find_a_recording(world, state, reader):
    build(world, state)
    found = "r1" in library_ids(reader)
    assert found == (reader in CASES[state][2])


@pytest.mark.parametrize("state", CASES)
@pytest.mark.parametrize("reader", [MEMBER, OUTSIDER])
def test_an_answer_never_cites_what_the_reader_may_not_read(world, state, reader):
    build(world, state)
    cited = "r1" in asked_ids(reader)
    assert cited == (reader in CASES[state][2])


@pytest.mark.parametrize("state", CASES)
@pytest.mark.parametrize("reader", [MEMBER, OUTSIDER, VISITOR])
def test_only_the_right_readers_can_play_the_audio(world, state, reader):
    build(world, state)
    assert plays(reader) == (reader in CASES[state][3])


@pytest.mark.parametrize("state", CASES)
def test_a_reader_who_may_not_find_a_recording_learns_nothing_about_it(world, state):
    """The refusal for an outsider is the same as for a recording that does not exist."""
    build(world, state)
    as_reader(OUTSIDER)
    client = TestClient(app)
    real = client.get("/v1/recordings/r1/media")
    unknown = client.get("/v1/recordings/does-not-exist/media")
    if real.status_code != 200:
        assert (real.status_code, real.json()) == (unknown.status_code, unknown.json())


@pytest.mark.parametrize("state", CASES)
def test_an_outsider_cannot_open_the_recording_record(world, state):
    """The record holds the transcript, versions and consent reference: never for an outsider."""
    build(world, state)
    assert as_reader(OUTSIDER).get("/v1/recordings/r1").status_code == 404


@pytest.mark.parametrize("state", CASES)
def test_a_visitor_cannot_open_the_recording_record_or_ask(world, state):
    build(world, state)
    app.dependency_overrides.pop(current_principal, None)
    client = TestClient(app)
    for response in (
        client.get("/v1/recordings/r1"),
        client.post("/v1/query", json={"question": "water"}),
    ):
        assert response.status_code in (401, 403, 503)  # 503: sign-in is not configured in tests
        assert "water" not in response.text
