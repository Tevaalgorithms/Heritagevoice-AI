"""Builders for indexing tests: published recordings with approved transcripts."""

from sqlalchemy.orm import Session

from app.db.repositories import (
    ConsentRepository,
    NewVersion,
    RecordingRepository,
    VersionRepository,
)
from app.models.records import (
    HeritageKind,
    Recording,
    RecordingStatus,
    Subject,
    VersionStatus,
    Visibility,
)
from app.models.transcript import Segment
from tests.helpers import consent

TAMIL = [
    Segment(segment_id="s1", start_s=0.0, end_s=4.0, text="கோடையில் ஏற்றம் வைத்து தண்ணீர் இறைப்போம்"),
    Segment(
        segment_id="s2", start_s=4.0, end_s=9.0, text="மழை குறைவாக இருந்தால் தண்ணீரைப் பகிர்ந்து கொள்வோம்"
    ),
]
ENGLISH = [
    Segment(segment_id="s1", start_s=0.0, end_s=4.0, text="In summer we drew water with the lever"),
    Segment(
        segment_id="s2",
        start_s=4.0,
        end_s=9.0,
        text="When rain was scarce everyone shared the water",
    ),
]


def add_consent(session: Session, consent_id="consent-1", community="c1", **kwargs) -> None:
    if ConsentRepository(session).get(consent_id) is None:
        ConsentRepository(session).add(consent(consent_id, community, **kwargs))


def published(session: Session, recording_id="r1", community="c1", **content) -> Recording:
    """A published recording whose transcript (and translation) are approved.

    Options: consent_id, consent (extra kwargs for the consent, e.g. rights), transcript (default
    TAMIL), translation (default ENGLISH, or None), language, kind, visibility, credit_name,
    source_kind, source_note.
    """
    consent_id = content.get("consent_id", "consent-1")
    transcript = content.get("transcript", TAMIL)
    translation = content.get("translation", ENGLISH)
    add_consent(session, consent_id, community, **content.get("consent", {}))
    recording = Recording(
        id=recording_id,
        community_id=community,
        uploader_id="uploader",
        language=content.get("language", "ta"),
        consent_id=consent_id,
        heritage_kind=content.get("kind", HeritageKind.STORY),
        visibility=content.get("visibility", Visibility.COMMUNITY),
        status=RecordingStatus.PUBLISHED,
        credit_name=content.get("credit_name"),
        source_kind=content.get("source_kind"),
        source_note=content.get("source_note"),
    )
    RecordingRepository(session).create(recording)
    versions = VersionRepository(session)
    versions.add_draft(NewVersion(recording_id, Subject.TRANSCRIPT, list(transcript), "system"))
    versions.set_status(recording_id, Subject.TRANSCRIPT, 1, VersionStatus.APPROVED)
    if translation is not None:
        draft = NewVersion(recording_id, Subject.TRANSLATION, list(translation), "system", 1)
        versions.add_draft(draft)
        versions.set_status(recording_id, Subject.TRANSLATION, 1, VersionStatus.APPROVED)
    return recording
