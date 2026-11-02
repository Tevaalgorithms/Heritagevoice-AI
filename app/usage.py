"""Count the tokens each model call uses, and turn the counts into an estimated cost.

A callback on the chat model reads the token counts the provider reports after every call, so each
job (translation, supervisor, verifier, answer, graph) is counted wherever it is called from. Only
numbers are stored. A problem while recording is logged and never breaks the call itself.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from sqlalchemy.orm import Session

from app.db.repositories.usage import UsageRepository
from app.models.llm import CatalogEntry
from app.models.usage import UsageLine, UsageSummary, UsageTotal

logger = logging.getLogger("heritagevoice.usage")
PER_MILLION = 1_000_000
SessionFactory = Callable[[], AbstractContextManager[Session]]


class UsageSink(Protocol):
    """Where token counts go. The real one is the database; tests use a list."""

    def record(self, role: str, model: str, input_tokens: int, output_tokens: int) -> None: ...


class UsageLog:
    """Stores one row per model call."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def record(self, role: str, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._sessions() as session:
            UsageRepository(session).add(role, model, input_tokens, output_tokens)


def _counts(response: LLMResult) -> tuple[int, int]:
    """Input and output tokens the provider reported across the result's messages."""
    used_in = used_out = 0
    for generations in response.generations:
        for generation in generations:
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
            used_in += int(usage.get("input_tokens", 0))
            used_out += int(usage.get("output_tokens", 0))
    return used_in, used_out


class UsageCallback(BaseCallbackHandler):
    """Reports the tokens of every call the chat model makes (retries are billed, so they count)."""

    def __init__(self, role: str, model: str, sink: UsageSink) -> None:
        self._role, self._model, self._sink = role, model, sink

    def on_llm_end(self, response: LLMResult, **_: Any) -> None:
        try:
            used_in, used_out = _counts(response)
            if used_in or used_out:
                self._sink.record(self._role, self._model, used_in, used_out)
        except Exception as error:  # counting must never break an answer
            logger.warning("%s: usage not recorded (%s)", self._role, type(error).__name__)


def _cost(total: UsageTotal, entry: CatalogEntry | None) -> float | None:
    if entry is None or entry.input_price is None or entry.output_price is None:
        return None
    return (
        total.input_tokens * entry.input_price + total.output_tokens * entry.output_price
    ) / PER_MILLION


def _priced(totals: list[UsageTotal], catalog: list[CatalogEntry]) -> list[UsageLine]:
    prices = {entry.model_id: entry for entry in catalog}
    return [UsageLine(**t.model_dump(), cost=_cost(t, prices.get(t.model))) for t in totals]


def _total_cost(lines: list[UsageLine]) -> float:
    return round(sum(line.cost for line in lines if line.cost is not None), 4)


def _unpriced(lines: list[UsageLine]) -> list[str]:
    return sorted({line.model for line in lines if line.cost is None})


def summarise(totals: list[UsageTotal], catalog: list[CatalogEntry], days: int) -> UsageSummary:
    """Add a cost to each line where the model has a price, and total everything."""
    lines = _priced(totals, catalog)
    return UsageSummary(
        days=days,
        lines=lines,
        calls=sum(line.calls for line in lines),
        input_tokens=sum(line.input_tokens for line in lines),
        output_tokens=sum(line.output_tokens for line in lines),
        cost=_total_cost(lines),
        unpriced_models=_unpriced(lines),
    )
