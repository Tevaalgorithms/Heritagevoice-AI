"""What a reader gets when something breaks: a safe, honest answer, never a guess or a leak.

Each case runs through the real API with a real database. The reader may see a warning or "not
enough in the recordings", but never an invented answer, a server error, or text from a prompt.
"""

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
from app.db.repositories import ConsentRepository
from app.db.session import session_scope
from app.db.tables import Base
from app.errors import ProviderError
from app.graph.workflow import Agents
from app.indexing import IndexDeps, index_one
from app.models.evidence import Route
from app.retrieval.delivery import DeliveryCheck
from tests.helpers import person
from tests.index_helpers import published
from tests.qa_helpers import Script, no_graph

URL = "/v1/query"
ASK = {"question": "shared the water"}
GOOD_ANSWER = AnswerDraft(answer="Water was shared [1].", claims_used=[1])


class Failing(Script):
    """A model that is down."""

    def invoke(self, inputs):
        self.calls.append(inputs)
        raise ProviderError("provider is down", code="model")


def verification():
    return Verification(
        claims=[ClaimCheck(text="Water was shared.", passages=["p1"])], coverage="full"
    )


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'failures.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        published(session, "r1", "c1")
    index_one(IndexDeps(lambda: session_scope(engine)), "r1")
    return engine


def serve(engine, **steps):
    """The real search over the database, with models that work unless a test breaks one."""
    agents = Agents(
        classify=steps.get("classify", Supervisor(Script(RouteDecision(route=Route.HYBRID)))),
        hybrid=steps.get("hybrid", HybridRetriever(lambda: session_scope(engine))),
        graph=no_graph,
        verify=steps.get("verify", Verifier(Script(verification()))),
        answer=steps.get("answer", AnswerAgent(Script(GOOD_ANSWER))),
        still_readable=DeliveryCheck(lambda: session_scope(engine)),
    )
    app.dependency_overrides[get_agents] = lambda: agents
    app.dependency_overrides[current_principal] = lambda: person(user_id="u", communities=("c1",))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()


def test_the_baseline_answers_with_a_citation(engine):
    body = serve(engine).post(URL, json=ASK).json()
    assert body["status"] == "answered"
    assert {c["recording_id"] for c in body["citations"]} == {"r1"}


def test_a_slow_question_is_stopped_at_the_deadline_and_reveals_nothing(engine, monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_QUERY_DEADLINE_S", "0.2")

    def slow(state, principal):
        time.sleep(1.0)
        return {"hybrid_evidence": []}

    response = serve(engine, hybrid=slow).post(URL, json=ASK)
    assert (response.status_code, response.json()["detail"]) == (504, {"code": "deadline"})
    assert "water" not in response.text


def test_when_the_router_is_down_the_text_is_searched_with_a_warning(engine):
    body = serve(engine, classify=Supervisor(Failing())).post(URL, json=ASK).json()
    assert body["status"] == "answered"
    assert "supervisor_unavailable" in body["warnings"]


def test_when_the_checker_is_down_nothing_is_claimed(engine):
    body = serve(engine, verify=Verifier(Failing())).post(URL, json=ASK).json()
    assert body["status"] == "insufficient_evidence"
    assert (body["answer"] and "Water was shared" in body["answer"]) is False
    assert body["citations"] == []


def test_when_the_writer_is_down_the_checked_claims_are_shown_as_they_are(engine):
    body = serve(engine, answer=AnswerAgent(Failing())).post(URL, json=ASK).json()
    assert body["status"] in ("answered", "partial")
    assert "Water was shared" in body["answer"]
    assert "answer_writer_unavailable" in body["warnings"]


def test_when_every_model_is_down_the_reader_is_told_there_is_not_enough(engine):
    client = serve(
        engine,
        classify=Supervisor(Failing()),
        verify=Verifier(Failing()),
        answer=AnswerAgent(Failing()),
    )
    response = client.post(URL, json=ASK)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []


def test_a_crash_inside_a_step_is_a_plain_server_error_that_leaks_no_text(engine):
    def broken(state, principal):
        raise RuntimeError("SECRET prompt text and database password")

    response = serve(engine, hybrid=broken).post(URL, json=ASK)
    assert response.status_code == 500
    assert "SECRET" not in response.text
    assert "password" not in response.text


def test_a_recording_withdrawn_while_the_question_runs_is_not_cited(engine):
    """Consent is withdrawn after the passage was found but before the answer is returned."""

    class Withdraws(Verifier):
        def __call__(self, state):
            with session_scope(engine) as session:
                ConsentRepository(session).revoke("consent-1")
            return super().__call__(state)

    response = serve(engine, verify=Withdraws(Script(verification()))).post(URL, json=ASK)
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert "Water was shared" not in body["answer"]
    assert "sources_changed" in body["warnings"]


def test_an_untouched_recording_is_still_cited_after_the_last_look(engine):
    body = serve(engine).post(URL, json=ASK).json()
    assert body["status"] == "answered"
    assert "sources_changed" not in body["warnings"]
