"""Recordings and their lifecycle status."""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.tables import (
    RecordingRow,
)
from app.models.credit import SourceKind
from app.models.library import LibraryFilter
from app.models.records import (
    HeritageKind,
    Recording,
    RecordingStatus,
    Visibility,
)


def _to_recording(row: RecordingRow) -> Recording:
    return Recording(
        id=row.id,
        community_id=row.community_id,
        uploader_id=row.uploader_id,
        language=row.language,
        consent_id=row.consent_id,
        heritage_kind=HeritageKind(row.heritage_kind),
        visibility=Visibility(row.visibility),
        status=RecordingStatus(row.status),
        audio_key=row.audio_key,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_s=row.duration_s,
        credit_name=row.credit_name,
        source_kind=SourceKind(row.source_kind) if row.source_kind else None,
        source_note=row.source_note,
        added=row.created_at.date().isoformat() if row.created_at else "",
    )


@dataclass(frozen=True)
class Media:
    """The stored audio of a recording and the note about where it came from."""

    audio_key: str
    content_type: str
    size_bytes: int
    duration_s: float
    source_note: str | None = None


class RecordingRepository:
    """Stores recordings and finds them by ID, uploader or idempotency key."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, recording: Recording, idempotency_key: str | None = None) -> Recording:
        self._session.add(
            RecordingRow(
                **recording.model_dump(mode="json", exclude={"added"}),
                idempotency_key=idempotency_key,
            )
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

    def list_owned_in(self, owner_id: str, community: str) -> list[Recording]:
        """One person's own recordings in one community (used for open sharing)."""
        query = (
            select(RecordingRow)
            .where(RecordingRow.community_id == community, RecordingRow.uploader_id == owner_id)
            .order_by(RecordingRow.created_at.desc())
            .limit(200)
        )
        return [_to_recording(r) for r in self._session.scalars(query)]

    def get_many(self, recording_ids: list[str]) -> dict[str, Recording]:
        if not recording_ids:
            return {}
        query = select(RecordingRow).where(RecordingRow.id.in_(recording_ids))
        return {row.id: _to_recording(row) for row in self._session.scalars(query)}

    def list_visible(self, communities: frozenset[str], where: LibraryFilter) -> list[Recording]:
        """Published recordings this reader may see: public ones, plus their own communities'."""
        query = select(RecordingRow).where(
            RecordingRow.status == RecordingStatus.PUBLISHED,
            or_(
                RecordingRow.visibility == Visibility.PUBLIC,
                RecordingRow.community_id.in_(communities),
            ),
        )
        if where.language is not None:
            query = query.where(RecordingRow.language == where.language)
        if where.kind is not None:
            query = query.where(RecordingRow.heritage_kind == where.kind)
        query = query.order_by(RecordingRow.created_at.desc(), RecordingRow.id).limit(where.limit)
        return [_to_recording(r) for r in self._session.scalars(query)]

    def set_visibility(self, recording_id: str, visibility: Visibility) -> None:
        row = self._session.get(RecordingRow, recording_id)
        if row is None:
            raise KeyError(recording_id)
        row.visibility = visibility
        self._session.flush()

    def list_all(self, limit: int = 200) -> list[Recording]:
        """Every recording, newest first. For admins, who review across communities."""
        query = select(RecordingRow).order_by(RecordingRow.created_at.desc()).limit(limit)
        return [_to_recording(r) for r in self._session.scalars(query)]

    def ids_by_status(self, status: RecordingStatus) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.status == status)
        return sorted(self._session.scalars(query))

    def ids_by_consent(self, consent_id: str) -> list[str]:
        query = select(RecordingRow.id).where(RecordingRow.consent_id == consent_id)
        return list(self._session.scalars(query))

    def set_media(self, recording_id: str, media: Media) -> None:
        """Attach audio, and a source note, to a recording that was added without them."""
        row = self._session.get(RecordingRow, recording_id)
        if row is None:
            raise KeyError(recording_id)
        row.audio_key = media.audio_key
        row.content_type = media.content_type
        row.size_bytes = media.size_bytes
        row.duration_s = media.duration_s
        row.source_note = media.source_note

    def set_status(self, recording_id: str, status: RecordingStatus) -> None:
        row = self._session.get(RecordingRow, recording_id)
        if row is None:
            raise KeyError(recording_id)
        row.status = status
