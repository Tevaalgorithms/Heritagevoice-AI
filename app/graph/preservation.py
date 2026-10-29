"""Preservation graph (ingestion supervisor skeleton): audio to a reviewable draft.

queued -> transcribing -> translating -> review. Any provider failure becomes an explicit
`failed` state with a safe error code; nothing is published or indexed from here.
"""

from collections.abc import Callable
from functools import partial
from typing import Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.errors import ProviderError
from app.graph.state import PreservationState, StateUpdate
from app.models.job import JobStatus
from app.models.records import Right
from app.ports import Transcriber, Translator
from app.security.consent import ConsentDeniedError, require_right


class Step(Protocol):
    """A graph node; the parameter name matches what LangGraph expects."""

    def __call__(self, state: PreservationState) -> StateUpdate: ...


def _failed(code: str) -> StateUpdate:
    return {"status": JobStatus.FAILED, "error": code}


def _guarded(step: Callable[[PreservationState], StateUpdate], error_code: str) -> Step:
    def run(state: PreservationState) -> StateUpdate:
        try:
            return step(state)
        except ConsentDeniedError:
            return _failed("consent")
        except ProviderError:
            return _failed(error_code)

    return run


def transcribe(state: PreservationState, transcriber: Transcriber) -> StateUpdate:
    require_right(state.get("consent"), Right.AI_PROCESSING)
    segments = transcriber.transcribe(state["audio"], state["language"])
    return {"segments": segments, "status": JobStatus.PROCESSING}


def translate(state: PreservationState, translator: Translator) -> StateUpdate:
    require_right(state.get("consent"), Right.TRANSLATION)
    translations = translator.translate(state["segments"], "en")
    return {"translations": translations, "status": JobStatus.REVIEW}


def continue_unless_failed(state: PreservationState) -> str:
    return END if state.get("status") == JobStatus.FAILED else "translate"


def build_preservation_graph(
    transcriber: Transcriber, translator: Translator
) -> CompiledStateGraph[PreservationState]:
    builder = StateGraph(PreservationState)
    builder.add_node("transcribe", _guarded(partial(transcribe, transcriber=transcriber), "asr"))
    builder.add_node("translate", _guarded(partial(translate, translator=translator), "mt"))
    builder.add_edge(START, "transcribe")
    builder.add_conditional_edges("transcribe", continue_unless_failed, ["translate", END])
    builder.add_edge("translate", END)
    return builder.compile()
