"""Change who may read a recording: its community only, or every signed-in user."""

from sqlalchemy.orm import Session

from app.db.repositories import ConsentRepository, RecordingRepository
from app.index_sync import queue_index
from app.models.records import Recording, RecordingStatus, Right, Visibility
from app.security.consent import require_right


def change_visibility(session: Session, recording: Recording, visibility: Visibility) -> None:
    """Going public needs the community's public-sharing consent. Published content is queued to
    be re-indexed so its search entries carry the new visibility; until then the eligibility gate
    already reads the recording's current setting, so a change to private takes effect at once."""
    if visibility is Visibility.PUBLIC:
        require_right(ConsentRepository(session).get(recording.consent_id), Right.PUBLIC_SHARING)
    RecordingRepository(session).set_visibility(recording.id, visibility)
    if recording.status is RecordingStatus.PUBLISHED:
        queue_index(session, recording.id)
