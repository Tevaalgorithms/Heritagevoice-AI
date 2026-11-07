"""Assemble the real question-answering agents from settings."""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.adapters.llm_runner import ModelRunner, structured_chain
from app.agents.answer_agent import AnswerAgent, AnswerDraft
from app.agents.graph_rag import GraphRetriever
from app.agents.hybrid_rag import HybridRetriever
from app.agents.prompts.answer import ANSWER_PROMPT
from app.agents.prompts.rewrite import REWRITE_PROMPT
from app.agents.prompts.supervisor import SUPERVISOR_PROMPT
from app.agents.prompts.verifier import VERIFIER_PROMPT
from app.agents.rewriter import QuestionRewriter, Standalone
from app.agents.supervisor import RouteDecision, Supervisor
from app.agents.verifier import Verification, Verifier
from app.budget import GuardedUsageLog
from app.config import Settings
from app.credits import OriginLookup
from app.graph.workflow import Agents
from app.graph_setup import RuntimeGraphReader
from app.model_registry import ModelRegistry
from app.models.llm import ModelRole
from app.ports import VectorStore
from app.retrieval.delivery import DeliveryCheck
from app.secrets import SecretReader, secrets_for

SessionFactory = Callable[[], AbstractContextManager[Session]]


def build_agents(
    settings: Settings,
    sessions: SessionFactory,
    vectors: VectorStore | None,
    secrets: SecretReader | None = None,
) -> Agents:
    """The real agents: each model call goes through the job's models and fall-backs."""
    registry = ModelRegistry(sessions, settings)
    usage = GuardedUsageLog(sessions)
    keys = secrets or secrets_for(settings)
    graph = RuntimeGraphReader(keys)

    def runner(role: ModelRole, prompt, schema) -> ModelRunner:  # type: ignore[no-untyped-def]
        return ModelRunner(registry, keys, role, structured_chain(prompt, schema, usage))

    return Agents(
        classify=Supervisor(
            runner(ModelRole.SUPERVISOR, SUPERVISOR_PROMPT, RouteDecision), graph.enabled
        ),
        hybrid=HybridRetriever(sessions, vectors),
        graph=GraphRetriever(sessions, graph.get),
        verify=Verifier(runner(ModelRole.VERIFIER, VERIFIER_PROMPT, Verification)),
        answer=AnswerAgent(runner(ModelRole.ANSWER, ANSWER_PROMPT, AnswerDraft)),
        rewrite=QuestionRewriter(runner(ModelRole.SUPERVISOR, REWRITE_PROMPT, Standalone)),
        still_readable=DeliveryCheck(sessions),
        origins=OriginLookup(sessions),
    )
