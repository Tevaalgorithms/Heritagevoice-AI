"""Turn a follow-up question into one that stands alone, using the earlier turns of the chat.

The earlier turns come from the page and are only wording to understand a pronoun or a topic; they
carry no access rights and never reach retrieval as anything but part of the rewritten question,
which is searched exactly like any other question. With no history there is no model call, and if
the model fails the original question is used, so a follow-up never breaks the answer.
"""

import logging
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.errors import ProviderError
from app.models.evidence import Turn
from app.ports import Invoker

logger = logging.getLogger("heritagevoice.agents")
MAX_QUESTION = 1000


class Standalone(BaseModel):
    """The model's rewritten question."""

    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION)]


def _conversation(history: list[Turn]) -> str:
    return "\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)


class QuestionRewriter:
    """Makes follow-up questions searchable on their own."""

    def __init__(self, runner: Invoker) -> None:
        self._runner = runner

    def __call__(self, question: str, history: list[Turn]) -> str:
        if not history:
            return question
        inputs = {"conversation": _conversation(history), "question": question}
        try:
            result: Any = self._runner.invoke(inputs)
        except ProviderError:
            return question
        return result.question if isinstance(result, Standalone) else question
