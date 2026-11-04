"""Understand a reviewer's spoken correction of a proposed relationship.

The model only suggests. The reviewer sees the words it heard and the relationship it wrote, can
change either, and approves it themselves. An answer that does not make sense is dropped.
"""

from typing import Any

from pydantic import BaseModel

from app.errors import ProviderError
from app.models.records import GraphAssertion, Relation
from app.ports import Invoker

CORRECTION = "correction"
MAX_NAME = 200


class Interpretation(BaseModel):
    """The relationship the reviewer asked for, or `understood=False` if it was unclear."""

    understood: bool
    subject: str = ""
    relation: Relation = Relation.RELATED_TO
    object: str = ""


def _usable(found: Interpretation) -> bool:
    subject, obj = found.subject.strip(), found.object.strip()
    names_ok = 0 < len(subject) <= MAX_NAME and 0 < len(obj) <= MAX_NAME
    return (
        found.understood
        and names_ok
        and subject.casefold() != obj.casefold()
        and found.relation is not Relation.SUPPORTED_BY  # support links are added by the system
    )


def _clean(found: Interpretation) -> Interpretation:
    return found.model_copy(
        update={
            "subject": " ".join(found.subject.split()),
            "object": " ".join(found.object.split()),
        }
    )


class CorrectionInterpreter:
    """Asks the model what the spoken correction means for one proposal."""

    def __init__(self, runner: Invoker) -> None:
        self._runner = runner

    def interpret(
        self, current: GraphAssertion, passage: str, heard: str, english: str
    ) -> Interpretation | None:
        proposed = f"{current.subject} | {current.relation.value} | {current.object}"
        result: Any = self._runner.invoke(
            {"passage": passage, "proposed": proposed, "heard": heard, "english": english}
        )
        if not isinstance(result, Interpretation):
            raise ProviderError("unexpected correction output", code=CORRECTION)
        return _clean(result) if _usable(result) else None
