"""POST /v1/query: who may ask, what comes back, and what never leaves."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.agents.answer_agent import AnswerAgent, AnswerDraft
from app.agents.hybrid_rag import HybridRetriever
from app.agents.supervisor import RouteDecision, Supervisor
from app.agents.verifier import ClaimCheck, Verification, Verifier
from app.api.auth import current_principal
from app.api.main import app
from app.api.query import get_agents
from app.db.session import session_scope
from app.db.tables import Base
from app.graph.workflow import Agents
from app.indexing import IndexDeps, index_one
from app.models.evidence import Route
from app.models.records import REMEDY_NOTICE
from tests.helpers import person
from tests.index_helpers import published
from tests.qa_helpers import READER, Retriever, Script, no_graph, passage

URL = "/v1/query"
ASK = {"question": "How was water shared?"}


def full(label="p1"):
    return Verification(
        claims=[ClaimCheck(text="Water was shared.", passages=[label])], coverage="full"
    )


def serving(agents: Agents):
    app.dependency_overrides[get_agents] = lambda: agents


def agents_object(items, route=Route.HYBRID):
    from app.agents.answer_agent import AnswerAgent  # noqa: PLC0415
    from app.agents.supervisor import Supervisor  # noqa: PLC0415
    from app.agents.verifier import Verifier  # noqa: PLC0415
    from tests.qa_helpers import Script, no_graph  # noqa: PLC0415

    return Agents(
        classify=Supervisor(Script(RouteDecision(route=route))),
        hybrid=Retriever({}, default=items),
        graph=no_graph,
        verify=Verifier(Script(full())),
        answer=AnswerAgent(Script(AnswerDraft(answer="Water was shared [1].", claims_used=[1]))),
    )


@pytest.fixture
def client():
    app.dependency_overrides[current_principal] = lambda: READER
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_question_returns_a_cited_answer(client):
    serving(agents_object([passage("e1")]))
    body = client.post(URL, json=ASK).json()
    assert body["status"] == "answered"
    assert body["answer"] == "Water was shared [1]."
    assert [c["evidence_id"] for c in body["citations"]] == ["e1"]
    assert body["request_id"]


def test_a_citation_gives_the_passage_and_its_time_but_nothing_internal(client):
    serving(agents_object([passage("e1")]))
    (citation,) = client.post(URL, json=ASK).json()["citations"]
    assert citation["passage"] == "water was shared"
    assert (citation["start_s"], citation["end_s"]) == (0.0, 4.0)
    assert set(citation) == {
        "evidence_id",
        "recording_id",
        "title",
        "passage",
        "start_s",
        "end_s",
        "notices",
    }


def test_the_response_never_names_a_community_an_access_label_or_a_storage_path(client):
    serving(agents_object([passage("e1")]))
    text = client.post(URL, json=ASK).text
    for leaked in ("community:", "access_groups", '"c1"', "audio_key", "recordings/", "uploader"):
        assert leaked not in text


def test_a_remedy_notice_reaches_the_reader_in_the_answer_and_on_the_citation(client):
    remedy = passage("e1").model_copy(update={"notices": (REMEDY_NOTICE,)})
    serving(agents_object([remedy]))
    body = client.post(URL, json=ASK).json()
    assert REMEDY_NOTICE in body["answer"]
    assert body["citations"][0]["notices"] == [REMEDY_NOTICE]


def test_no_passages_is_an_honest_insufficient_evidence_answer_not_an_error(client):
    serving(agents_object([]))
    response = client.post(URL, json=ASK)
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["citations"] == []


def test_warnings_are_reported_once(client):
    serving(agents_object([passage("e1")], route=Route.GRAPH))
    assert client.post(URL, json=ASK).json()["warnings"] == ["graph_unavailable"]


def test_a_reader_with_no_community_cannot_ask(client):
    app.dependency_overrides[current_principal] = lambda: person(user_id="x", communities=())
    serving(agents_object([passage("e1")]))
    assert client.post(URL, json=ASK).status_code == 403


def test_asking_needs_a_signed_in_user():
    app.dependency_overrides.clear()
    assert TestClient(app).post(URL, json=ASK).status_code in {401, 503}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": "x" * 8001},
        {**ASK, "role": "admin"},
        {**ASK, "groups": ["x"]},
    ],
    ids=["missing", "empty", "too-long", "role", "groups"],
)
def test_a_malformed_question_is_rejected(client, body):
    serving(agents_object([passage("e1")]))
    assert client.post(URL, json=body).status_code == 422


def test_a_question_that_takes_too_long_is_cut_off_with_a_timeout(client, monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_QUERY_DEADLINE_S", "0.05")

    def slow(state, principal):
        time.sleep(0.4)
        return {"hybrid_evidence": []}

    agents = agents_object([passage("e1")])
    serving(Agents(agents.classify, slow, agents.graph, agents.verify, agents.answer))
    response = client.post(URL, json=ASK)
    assert (response.status_code, response.json()["detail"]["code"]) == (504, "deadline")


def test_a_failed_permission_check_inside_the_graph_is_a_generic_503_that_leaks_nothing(client):
    hidden = passage("e1", groups=("community:other",))
    serving(agents_object([hidden]))
    response = client.post(URL, json=ASK)
    assert (response.status_code, response.json()["detail"]) == (503, {"code": "unavailable"})
    assert "other" not in response.text


def test_agents_that_are_not_wired_answer_503():
    app.dependency_overrides[current_principal] = lambda: READER
    from app.agents.supervisor import classify  # noqa: PLC0415

    agents = agents_object([passage("e1")])
    serving(Agents(classify, agents.hybrid, agents.graph, agents.verify, agents.answer))
    try:
        assert TestClient(app).post(URL, json=ASK).status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_the_conversation_id_is_echoed_back(client):
    serving(agents_object([passage("e1")]))
    body = client.post(URL, json={**ASK, "conversation_id": "conv-1"}).json()
    assert body["conversation_id"] == "conv-1"


# --- the whole path against a real database --------------------------------------------------


@pytest.fixture
def database_agents(tmp_path):
    """A community with one published, indexed recording, and agents that search it."""
    engine = create_engine(f"sqlite:///{tmp_path / 'qa.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        published(session, "r1", "c1")
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")
    verifier = Script(full())
    writer = Script(AnswerDraft(answer="Water was shared [1].", claims_used=[1]))
    agents = Agents(
        classify=Supervisor(Script(RouteDecision(route=Route.HYBRID))),
        hybrid=HybridRetriever(lambda: session_scope(engine)),
        graph=no_graph,
        verify=Verifier(verifier),
        answer=AnswerAgent(writer),
    )
    app.dependency_overrides[get_agents] = lambda: agents
    yield agents, verifier, writer
    app.dependency_overrides.clear()


def ask_as(communities):
    app.dependency_overrides[current_principal] = lambda: person(
        user_id="u", communities=communities
    )
    return TestClient(app).post(URL, json={"question": "shared the water"}).json()


def test_a_reader_in_the_community_gets_a_cited_answer_from_the_real_database(database_agents):
    body = ask_as(("c1",))
    assert body["status"] == "answered"
    assert {c["recording_id"] for c in body["citations"]} == {"r1"}


def test_an_outsider_is_told_there_is_not_enough_and_no_model_is_asked(database_agents):
    _, verifier, writer = database_agents
    body = ask_as(("c9",))
    assert body["status"] == "insufficient_evidence"
    assert (verifier.calls, writer.calls) == ([], [])
