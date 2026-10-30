"""Fakes for question-answering tests: scripted models and a scripted search."""

from app.agents.answer_agent import AnswerAgent
from app.agents.supervisor import Supervisor
from app.agents.verifier import Verifier
from app.graph.workflow import Agents, build_workflow
from app.models.evidence import Evidence
from tests.helpers import person

READER = person(user_id="reader", communities=("c1",))


class Script:
    """A fake model that returns its answers in order and records its inputs."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def invoke(self, inputs):
        self.calls.append(inputs)
        return self.results.pop(0)


def passage(evidence_id, text="water was shared", groups=("community:c1",)):
    return Evidence(
        evidence_id=evidence_id,
        document_id=f"rec-{evidence_id}",
        document_version="v1",
        chunk_id="transcript:0",
        title="Recording",
        locator=f"audio:rec-{evidence_id}?t=0.0-4.0",
        passage=text,
        passage_hash="h",
        access_groups=frozenset(groups),
        retrieval_methods=frozenset({"bm25"}),
    )


class Retriever:
    """A fake hybrid search: returns what it is told per query and records the queries."""

    def __init__(self, by_query, default=()):
        self.by_query, self.default, self.queries = by_query, list(default), []

    def __call__(self, state, principal):
        query = state.get("search_query") or state["question"]
        self.queries.append(query)
        return {"hybrid_evidence": list(self.by_query.get(query, self.default))}


def no_graph(state, principal):
    return {"graph_evidence": []}


def build(route, verification, draft, retriever):
    supervisor, verifier, writer = Script(route), Script(*verification), Script(*draft)
    agents = Agents(
        classify=Supervisor(supervisor),
        hybrid=retriever,
        graph=no_graph,
        verify=Verifier(verifier),
        answer=AnswerAgent(writer),
    )
    return build_workflow(READER, agents=agents), supervisor, verifier, writer
