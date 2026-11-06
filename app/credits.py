"""What a reader may be told about where a recording came from.

The date it was added is always shown. The credit (who to thank, who told it, a book or a website)
is shown only while the recording's consent includes the attribution right. If that right was never
given, or the consent is withdrawn, the credit stays private and readers see the date only.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import ConsentRepository, RecordingRepository
from app.models.credit import Credit
from app.models.records import Consent, Recording, Right

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class Origin:
    """What a reader sees about a recording besides its words."""

    added: str
    heritage_kind: str
    language: str
    credit: Credit | None


def credit_for(recording: Recording, consent: Consent | None) -> Credit | None:
    """The credit to show, or None when the consent does not allow it or there is none."""
    if consent is None or not consent.permits(Right.ATTRIBUTION):
        return None
    credit = Credit(
        name=recording.credit_name,
        source_kind=recording.source_kind,
        source_note=recording.source_note,
    )
    return None if credit.is_empty() else credit


class OriginLookup:
    """Looks up the origin of each recording an answer cites, from PostgreSQL at answer time."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def __call__(self, recording_ids: list[str]) -> dict[str, Origin]:
        with self._sessions() as session:
            return origins_in(session, recording_ids)


def origins_in(session: Session, recording_ids: list[str]) -> dict[str, Origin]:
    """The origin of each of these recordings, read in this session."""
    recordings = RecordingRepository(session).get_many(sorted(set(recording_ids)))
    consents = ConsentRepository(session)
    return {
        rid: Origin(
            added=rec.added,
            heritage_kind=rec.heritage_kind.value,
            language=rec.language,
            credit=credit_for(rec, consents.get(rec.consent_id)),
        )
        for rid, rec in recordings.items()
    }
