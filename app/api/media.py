"""Play a recording. The audio is read from private storage only after the same checks as reading
the recording, plus two more: the recording is not revoked and its consent still allows playback.
Nothing is cached, and the storage address is never given out."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.recordings import NOT_FOUND, PathId, get_audio_store, viewable
from app.audio import sniff_type
from app.db.repositories import ConsentRepository
from app.models.records import Recording, RecordingStatus, Right
from app.ports import AudioStore
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action

router = APIRouter(prefix="/v1", tags=["recordings"])


def _playable(principal: Principal, recording: Recording, allowed: bool) -> bool:
    resource = Resource(recording.community_id, recording.uploader_id)
    return (
        allowed
        and recording.status != RecordingStatus.REVOKED
        and recording.audio_key is not None
        and authorize(principal, Action.MEDIA_PLAY, resource).allowed
    )


@router.get("/recordings/{recording_id}/media")
def recording_media(
    recording_id: Annotated[str, PathId],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> Response:
    with factory() as session:
        recording = viewable(session, principal, recording_id)
        consent = ConsentRepository(session).get(recording.consent_id)
        allowed = consent is not None and consent.permits(Right.PLAYBACK)
    if not _playable(principal, recording, allowed) or recording.audio_key is None:
        raise NOT_FOUND
    data = store.get(recording.audio_key)
    kind = sniff_type(data[:16])
    if kind is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(data, media_type=kind, headers={"Cache-Control": "private, no-store"})
