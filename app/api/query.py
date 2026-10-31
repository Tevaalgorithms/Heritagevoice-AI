"""Ask a question. The answer is built only from what the reader may read, and is cited."""

import asyncio
import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.auth import require_action
from app.api.tracing import current_trace_id
from app.config import IntegrationNotConfiguredError, Settings
from app.db.engine import engine_from_settings
from app.db.session import session_scope
from app.graph.workflow import Agents
from app.models.evidence import QueryRequest, QueryResponse
from app.qa import Ask, answer_question
from app.qa_setup import build_agents
from app.security.permissions import Principal
from app.security.roles import Action
from app.vector_setup import vector_store_for

router = APIRouter(prefix="/v1", tags=["query"])
logger = logging.getLogger("heritagevoice.query")


@lru_cache(maxsize=1)
def _production_agents() -> Agents:
    settings = Settings()
    engine = engine_from_settings(settings)
    return build_agents(settings, lambda: session_scope(engine), vector_store_for(settings, engine))


def get_agents() -> Agents:
    """The agents for this process. Overridden in tests; 503 when no database is configured."""
    try:
        return _production_agents()
    except IntegrationNotConfiguredError as error:
        raise HTTPException(status_code=503, detail={"code": "unavailable"}) from error


def ask_from(payload: QueryRequest) -> Ask:
    return Ask(payload.question, payload.response_language, payload.history)


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "unavailable"})


@router.post("/query")
async def ask(
    payload: QueryRequest,
    principal: Annotated[Principal, Depends(require_action(Action.QUERY_ASK))],
    agents: Annotated[Agents, Depends(get_agents)],
) -> QueryResponse:
    """Answer within the deadline. A reader never sees more than their own access allows."""
    deadline = Settings().query_deadline_s
    try:
        outcome = await asyncio.wait_for(
            run_in_threadpool(answer_question, ask_from(payload), principal, agents),
            deadline,
        )
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail={"code": "deadline"}) from error
    except (PermissionError, IntegrationNotConfiguredError) as error:
        logger.error("question could not be answered: %s", type(error).__name__)
        raise _unavailable() from error
    return QueryResponse(
        status=outcome.status,
        answer=outcome.answer,
        citations=outcome.citations,
        warnings=outcome.warnings,
        request_id=current_trace_id(),
        conversation_id=payload.conversation_id,
    )
