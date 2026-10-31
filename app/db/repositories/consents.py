"""Consent records: what a community has allowed for a recording."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import (
    ConsentRow,
)
from app.models.records import (
    Consent,
    Right,
)


def _to_consent(row: ConsentRow) -> Consent:
    return Consent(
        id=row.id,
        community_id=row.community_id,
        rights=frozenset(Right(r) for r in row.rights),
        policy_version=row.policy_version,
        revoked=row.revoked,
    )


class ConsentRepository:
    """Stores consent records and marks them revoked."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, consent: Consent) -> None:
        self._session.add(
            ConsentRow(
                id=consent.id,
                community_id=consent.community_id,
                rights=sorted(r.value for r in consent.rights),
                policy_version=consent.policy_version,
                revoked=consent.revoked,
            )
        )
        self._session.flush()

    def get(self, consent_id: str) -> Consent | None:
        row = self._session.get(ConsentRow, consent_id)
        return None if row is None else _to_consent(row)

    def for_communities(self, community_ids: list[str]) -> list[Consent]:
        """The consents of these groups, oldest first."""
        query = (
            select(ConsentRow)
            .where(ConsentRow.community_id.in_(community_ids))
            .order_by(ConsentRow.id)
        )
        return [_to_consent(row) for row in self._session.scalars(query)]

    def revoke(self, consent_id: str) -> bool:
        """Mark the consent revoked; False if it does not exist. Idempotent."""
        row = self._session.get(ConsentRow, consent_id)
        if row is None:
            return False
        row.revoked = True
        self._session.flush()
        return True
