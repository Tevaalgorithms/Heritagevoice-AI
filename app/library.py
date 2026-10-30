"""The Library: what a signed-in person may browse or search, in the language they choose.

Everything shown passes the same eligibility gate as search: published, consent still valid, the
current approved version, and either the reader's own community or public. Remedies carry a fixed
notice, and a contributor's community is named only when the consent allows attribution.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import ChunkRepository, ConsentRepository, RecordingRepository
from app.models.index import ChunkKind, ChunkRecord
from app.models.library import LibraryFilter, LibraryView
from app.models.records import REMEDY_NOTICE, HeritageKind, Recording, Right
from app.retrieval.eligibility import eligible_chunks
from app.retrieval.lexical import lexical_search
from app.security.permissions import Principal

CANDIDATE_FACTOR = 3
VIEW_KIND = {
    LibraryView.ORIGINAL: ChunkKind.TRANSCRIPT,
    LibraryView.TRANSLATION: ChunkKind.TRANSLATION,
}


@dataclass(frozen=True)
class LibraryEntry:
    """One passage to show, with enough context to read it responsibly."""

    evidence_id: str
    recording_id: str
    heritage_kind: HeritageKind
    language: str
    view: LibraryView
    passage: str
    start_s: float
    end_s: float
    notices: tuple[str, ...]
    community: str | None


def _notices(recording: Recording) -> tuple[str, ...]:
    return (REMEDY_NOTICE,) if recording.heritage_kind is HeritageKind.REMEDY else ()


def _community(session: Session, recording: Recording) -> str | None:
    """Named only if the people who gave the recording agreed to be credited."""
    consent = ConsentRepository(session).get(recording.consent_id)
    return recording.community_id if consent and consent.permits(Right.ATTRIBUTION) else None


def _entry(
    session: Session, chunk: ChunkRecord, recording: Recording, view: LibraryView
) -> LibraryEntry:
    return LibraryEntry(
        evidence_id=chunk.evidence_id,
        recording_id=recording.id,
        heritage_kind=recording.heritage_kind,
        language=recording.language,
        view=view,
        passage=chunk.text,
        start_s=chunk.start_s,
        end_s=chunk.end_s,
        notices=_notices(recording),
        community=_community(session, recording),
    )


def _matches(recording: Recording, where: LibraryFilter) -> bool:
    language_ok = where.language is None or recording.language == where.language
    return language_ok and (where.kind is None or recording.heritage_kind is where.kind)


def _entries(
    session: Session, chunks: list[ChunkRecord], where: LibraryFilter, principal: Principal
) -> list[LibraryEntry]:
    allowed = eligible_chunks(session, chunks, principal.communities)
    recordings = RecordingRepository(session).get_many([c.recording_id for c in allowed])
    entries = [
        _entry(session, chunk, recordings[chunk.recording_id], where.view)
        for chunk in allowed
        if chunk.kind is VIEW_KIND[where.view] and _matches(recordings[chunk.recording_id], where)
    ]
    return entries[: where.limit]


def browse(session: Session, principal: Principal, where: LibraryFilter) -> list[LibraryEntry]:
    """The newest published recordings the reader may see, each with its opening passage."""
    recordings = RecordingRepository(session).list_visible(principal.communities, where)
    openings = ChunkRepository(session).openings([r.id for r in recordings], VIEW_KIND[where.view])
    chunks = [openings[r.id] for r in recordings if r.id in openings]
    return _entries(session, chunks, where, principal)


def search(
    session: Session, principal: Principal, query: str, where: LibraryFilter
) -> list[LibraryEntry]:
    """Passages that contain the query's words, best first, from what the reader may see."""
    ids = lexical_search(session, query, principal.communities, where.limit * CANDIDATE_FACTOR)
    return _entries(session, ChunkRepository(session).get_many(ids), where, principal)
