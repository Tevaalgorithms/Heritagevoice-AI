"""Assemble the real question-answering agents from settings."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.adapters.llm_runner import ModelRunner, structured_chain
from app.agents.answer_agent import AnswerAgent, AnswerDraft
from app.agents.hybrid_rag import HybridRetriever
from app.agents.prompts.answer import ANSWER_PROMPT
from app.agents.prompts.supervisor import SUPERVISOR_PROMPT
from app.agents.prompts.verifier import VERIFIER_PROMPT
from app.agents.supervisor import RouteDecision, Supervisor
from app.agents.verifier import Verification, Verifier
from app.config import Settings
from app.graph.state import StateUpdate, WorkflowState
from app.graph.workflow import Agents
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole
from app.ports import VectorStore
from app.secrets import SecretReader, secrets_for
from app.security.permissions import Principal

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _no_graph(state: WorkflowState, principal: Principal) -> StateUpdate:
    """The knowledge graph is not built yet (segments 07 and 08), so it finds nothing."""
    return {"graph_evidence": []}


def build_agents(
    settings: Settings,
    sessions: SessionFactory,
    vectors: VectorStore | None,
    secrets: SecretReader | None = None,
) -> Agents:
    """The real agents: each model call goes through the job's models and fall-backs."""
    registry = ModelRegistry(sessions, settings)
    keys = secrets or secrets_for(settings)

    def runner(role: ModelRole, prompt, schema) -> ModelRunner:  # type: ignore[no-untyped-def]
        return ModelRunner(registry, keys, role, structured_chain(prompt, schema))

    return Agents(
        classify=Supervisor(runner(ModelRole.SUPERVISOR, SUPERVISOR_PROMPT, RouteDecision)),
        hybrid=HybridRetriever(sessions, vectors),
        graph=_no_graph,
        verify=Verifier(runner(ModelRole.VERIFIER, VERIFIER_PROMPT, Verification)),
        answer=AnswerAgent(runner(ModelRole.ANSWER, ANSWER_PROMPT, AnswerDraft)),
    )
