"""The append-only audit log of administrative actions."""

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.db.tables import (
    AuditLogRow,
)


@dataclass(frozen=True)
class AuditEntry:
    """Who did what to whom. `detail` is a short admin-written note, never recording content."""

    actor_sub: str
    action: str
    target: str
    trace_id: str
    detail: str | None = None


class AuditRepository:
    """Appends audit entries; nothing here updates or deletes them."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, entry: AuditEntry) -> None:
        self._session.add(AuditLogRow(**asdict(entry)))
        self._session.flush()
