"""One last look at the database before an answer is returned.

A question can take many seconds. If a recording is withdrawn, taken down or corrected in that
time, the passage the answer used may no longer be readable. This asks PostgreSQL again, with the
same rules as search, which of the cited sources can still be read by this person.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.retrieval.evidence_store import hydrate
from app.security.permissions import Principal

SessionFactory = Callable[[], AbstractContextManager[Session]]


class DeliveryCheck:
    """Which of these cited sources may this reader still read, right now?"""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def __call__(self, evidence_ids: list[str], principal: Principal) -> set[str]:
        with self._sessions() as session:
            return {e.evidence_id for e in hydrate(session, evidence_ids, principal, "delivery")}
