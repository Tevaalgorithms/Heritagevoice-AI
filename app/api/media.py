"""Play a recording. The audio is read from private storage only after the same checks as reading
the recording, plus two more: the recording is not revoked and its consent still allows playback.
Nothing is cached, and the storage address is never given out.

Anyone may play a recording that its community has shared publicly (see `public_playable`); the
open endpoint for visitors without an account is in `app/api/public.py`."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.recordings import NOT_FOUND, PathId, get_audio_store
from app.audio import sniff_type
from app.db.repositories import ConsentRepository, RecordingRepository
from app.models.records import Consent, Recording, RecordingStatus, Right, Visibility
from app.ports import AudioStore
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action

router = APIRouter(prefix="/v1", tags=["recordings"])
PRIVATE = {"Cache-Control": "private, no-store"}


def _published_with_audio(recording: Recording | None) -> bool:
    return (
        recording is not None
        and recording.status is RecordingStatus.PUBLISHED
        and recording.audio_key is not None
    )


def _shared_publicly(recording: Recording, consent: Consent | None) -> bool:
    """Public playback needs the recording to be public and its consent, as it stands now, to
    allow both public sharing and playback."""
    return (
        consent is not None
        and recording.visibility is Visibility.PUBLIC
        and consent.permits(Right.PUBLIC_SHARING)
        and consent.permits(Right.PLAYBACK)
    )


def public_playable(session: Session, recording_id: str) -> Recording | None:
    """The recording, if anyone may play it right now: published (so not revoked or taken down),
    public, and its consent allows public sharing and playback. Otherwise None."""
    recording = RecordingRepository(session).get(recording_id)
    if not _published_with_audio(recording) or recording is None:
        return None
    consent = ConsentRepository(session).get(recording.consent_id)
    return recording if _shared_publicly(recording, consent) else None


def audio_response(store: AudioStore, recording: Recording, headers: dict[str, str]) -> Response:
    """The recording's audio, read from private storage. Not found if it is not a known format."""
    data = store.get(recording.audio_key or "")
    kind = sniff_type(data[:16])
    if kind is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(data, media_type=kind, headers=headers)


def _playable_state(principal: Principal, recording: Recording, resource: Resource) -> bool:
    """Anyone in the community may play what it has published; drafts only for those who may view
    them (the uploader, coordinators and admins)."""
    if recording.audio_key is None or recording.status is RecordingStatus.REVOKED:
        return False
    return (
        recording.status is RecordingStatus.PUBLISHED
        or authorize(principal, Action.RECORDING_VIEW, resource).allowed
    )


def _members_may_play(session: Session, principal: Principal, recording: Recording) -> bool:
    resource = Resource(recording.community_id, recording.uploader_id)
    consent = ConsentRepository(session).get(recording.consent_id)
    return (
        consent is not None
        and consent.permits(Right.PLAYBACK)
        and authorize(principal, Action.MEDIA_PLAY, resource).allowed
        and _playable_state(principal, recording, resource)
    )


def _playable(session: Session, principal: Principal, recording_id: str) -> Recording:
    """Public recordings play for anyone signed in; otherwise the community's own rules apply."""
    public = public_playable(session, recording_id)
    if public is not None:
        return public
    recording = RecordingRepository(session).get(recording_id)
    if recording is None or not _members_may_play(session, principal, recording):
        raise NOT_FOUND
    return recording


@router.get("/recordings/{recording_id}/media")
def recording_media(
    recording_id: Annotated[str, PathId],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> Response:
    with factory() as session:
        recording = _playable(session, principal, recording_id)
    return audio_response(store, recording, PRIVATE)
