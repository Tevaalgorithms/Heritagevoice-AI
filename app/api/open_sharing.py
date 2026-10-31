"""Open sharing: a contributor shares a recording with everyone, with no group involved.

The contributor gives the consent themselves, on the upload form, and confirms they have the right
to share the recording. The consent always includes what open sharing needs (AI transcription and
translation, search, public sharing); only playback and attribution are optional. It belongs to
the reserved `everyone` space, and the recording still waits for an admin to review it before
anyone can find it. Each consent is audit-logged with the person who gave it.
"""

from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.api.tracing import current_trace_id
from app.db.repositories import AuditEntry, AuditRepository, ConsentRepository
from app.models.groups import OPEN_COMMUNITY
from app.models.records import Consent, Right
from app.security.permissions import Principal, Resource, authorize
from app.security.roles import Action

router = APIRouter(prefix="/v1/open-sharing", tags=["open-sharing"])
POLICY_VERSION = "open-v1"
REQUIRED = frozenset(
    {
        Right.AI_PROCESSING,
        Right.TRANSLATION,
        Right.INDEXING,
        Right.SUMMARIZATION,
        Right.PUBLIC_SHARING,
    }
)


class OpenConsentRequest(BaseModel):
    """What the contributor agrees to. `confirm` must be true: they have the right to share."""

    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]
    playback: bool = True
    attribution: bool = False


class OpenConsent(BaseModel):
    """The consent that was recorded, to send with the upload."""

    consent_id: str
    community_id: str


def _rights(body: OpenConsentRequest) -> frozenset[Right]:
    optional = {Right.PLAYBACK: body.playback, Right.ATTRIBUTION: body.attribution}
    return REQUIRED | {right for right, chosen in optional.items() if chosen}


def uploader(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    """Anyone allowed to upload may share openly; no group is needed."""
    resource = Resource(OPEN_COMMUNITY, principal.user_id)
    if not authorize(principal, Action.RECORDING_UPLOAD, resource).allowed:
        raise HTTPException(status_code=403, detail="Not permitted")
    return principal


@router.post("/consent", status_code=201)
def give_consent(
    body: OpenConsentRequest,
    principal: Annotated[Principal, Depends(uploader)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> OpenConsent:
    consent = Consent(
        id=f"consent-{uuid4().hex[:16]}",
        community_id=OPEN_COMMUNITY,
        rights=_rights(body),
        policy_version=POLICY_VERSION,
    )
    with factory() as session:
        ConsentRepository(session).add(consent)
        entry = AuditEntry(
            principal.user_id, "consent:open", f"consent:{consent.id}", current_trace_id()
        )
        AuditRepository(session).record(entry)
    return OpenConsent(consent_id=consent.id, community_id=OPEN_COMMUNITY)
