"""Recordings and their lifecycle status."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tables import (
    RecordingRow,
)
from app.models.records import (
    HeritageKind,
    Recording,
    RecordingStatus,
)


def _to_recording(row: RecordingRow) -> Recording:
    return Recording(
        id=row.id,
        community_id=row.community_id,
        uploader_id=row.uploader_id,
        language=row.language,
        consent_id=row.consent_id,
        heritage_kind=HeritageKind(row.heritage_kind),
        status=RecordingStatus(row.status),
        audio_key=row.audio_key,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_s=row.duration_s,
    )


class RecordingRepository:
    """Stores recordings and finds them by ID, uploader or idempotency key."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, recording: Recording, idempotency_key: str | None = None) -> Recording:
        self._session.add(
            RecordingRow(**recording.model_dump(mode="json"), idempotency_key=idempotency_key)
        )
        self._session.flush()
        return recording

    def get(self, recording_id: str) -> Recording | None:
        row = self._session.get(RecordingRow, recording_id)
        return None if row is None else _to_recording(row)

    def find_by_idempotency(self, uploader_id: str, key: str) -> Recording | None:
        query = select(RecordingRow).where(
            RecordingRow.uploader_id == uploader_id, RecordingRow.idempotency_key == key
        )
        row = self._session.scalars(query).first()
        return None if row is None else _to_recording(row)

    def list_for(self, communities: frozenset[str], owner_id: str | None) -> list[Recording]:
        """Recordings in these communities; only the owner's own when `owner_id` is given."""
        query = select(RecordingRow).where(RecordingRow.community_id.in_(communities))
        if owner_id is not None:
            query = query.where(RecordingRow.uploader_id == owner_id)
        query = query.order_by(RecordingRow.created_at.desc()).limit(200)
        return [_to_recording(r) for r in self._session.scalars(query)]

    def ids_by_status(self, status: RecordingStatus) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.status == status)
        return sorted(self._session.scalars(query))

    def ids_by_consent(self, consent_id: str) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.consent_id == consent_id)
        return list(self._session.scalars(query))

    def set_status(self, recording_id: str, status: RecordingStatus) -> None:
        row = self._session.get(RecordingRow, recording_id)
        if row is None:
            raise KeyError(recording_id)
        row.status = status
