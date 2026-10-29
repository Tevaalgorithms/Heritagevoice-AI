"""Walking skeleton: one fixture goes upload -> review -> index -> ask -> cited answer.

Everything here is in-memory and deterministic. Real adapters replace the fakes one at a time
behind the same ports; the agents and graphs do not change.
Run it with: uv run python -m app.skeleton
"""

from typing import cast

from app.fakes import FakeGraphStore, FakeTranscriber, FakeTranslator, FakeVectorStore, fake_agents
from app.graph.preservation import build_preservation_graph
from app.graph.state import PreservationState, WorkflowState
from app.graph.workflow import Agents, build_workflow
from app.models.evidence import Evidence
from app.models.records import Consent, Right
from app.models.transcript import Segment
from app.ports import Transcriber
from app.publishing import publish_recording
from app.security.permissions import Principal

FIXTURE_SEGMENTS = [
    Segment(
        segment_id="s1", start_s=0.0, end_s=4.0, text="Synthetic elder describes seasonal wells."
    ),
    Segment(
        segment_id="s2", start_s=4.0, end_s=9.5, text="Synthetic speaker explains water sharing."
    ),
]
DEMO_PRINCIPAL = Principal(user_id="demo-user", groups=frozenset({"public"}), policy_version="v1")
PUBLIC = frozenset({"public"})
FULL_CONSENT = Consent(
    id="consent-1", community_id="demo", rights=frozenset(Right), policy_version="v1"
)


def graph_view(item: Evidence) -> Evidence:
    """The same passage as the graph branch would return it, with a one-edge path."""
    path = ((item.chunk_id, item.document_id),)
    return item.model_copy(update={"retrieval_methods": frozenset({"graph"}), "graph_paths": path})


class Skeleton:
    def __init__(self, transcriber: Transcriber | None = None) -> None:
        self.vector = FakeVectorStore()
        self.graph = FakeGraphStore()
        self.transcriber = transcriber or FakeTranscriber(FIXTURE_SEGMENTS)
        self.agents: Agents = fake_agents(self.vector, self.graph)

    def ingest(
        self,
        recording_id: str,
        audio_key: str = "fixture/audio",
        consent: Consent = FULL_CONSENT,
    ) -> PreservationState:
        graph = build_preservation_graph(self.transcriber, FakeTranslator())
        state: PreservationState = {
            "recording_id": recording_id,
            "consent": consent,
            "audio_key": audio_key,
            "language": "ta",
        }
        return cast(PreservationState, graph.invoke(state))

    def publish(self, state: PreservationState, approved: bool) -> list[Evidence]:
        items = publish_recording(state, approved, self.vector, PUBLIC)
        self.graph.add([graph_view(item) for item in items])
        return items

    def revoke(self, items: list[Evidence]) -> None:
        ids = [item.evidence_id for item in items]
        self.vector.delete(ids)
        self.graph.delete(ids)

    def ask(self, question: str, principal: Principal = DEMO_PRINCIPAL) -> WorkflowState:
        workflow = build_workflow(principal, agents=self.agents)
        return cast(WorkflowState, workflow.invoke({"question": question}))


def main() -> None:
    skeleton = Skeleton()
    draft = skeleton.ingest("rec-1")
    print(f"ingest status: {draft['status']} ({len(draft['segments'])} segments)")
    before = skeleton.ask("seasonal wells")
    print(f"before approval: {before['status']}")
    skeleton.publish(draft, approved=True)
    result = skeleton.ask("What did the elder say about seasonal wells?")
    print(f"after approval: {result['status']}\nanswer: {result['answer']}")
    for citation in result["citations"]:
        print(f"  cite {citation.evidence_id} at {citation.locator}")


if __name__ == "__main__":
    main()
