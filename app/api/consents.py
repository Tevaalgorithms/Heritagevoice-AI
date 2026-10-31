"""Consent records: create, read and revoke. Admin only; every change is audit-logged.

Revoking a consent also revokes the recordings that rely on it and stops their queued or running
jobs, so no further processing, indexing or playback happens.
"""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.admin import AdminContext, context_for
from app.db.repositories import AuditRepository, ConsentRepository
from app.models.records import Consent, Right
from app.revocation import revoke_consent
from app.security.permissions import Principal
from app.security.roles import Action, Role

router = APIRouter(prefix="/admin/consents", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.CONSENT_MANAGE))]
ConsentId = Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")
POLICY_VERSION = r"^[A-Za-z0-9._-]{1,32}$"
NOT_FOUND = HTTPException(status_code=404, detail="Not found")
NOT_PERMITTED = HTTPException(status_code=403, detail="Not permitted")


def _may_manage(principal: Principal, community_id: str) -> bool:
    """Admins manage every group's consents; coordinators only their own groups'."""
    return principal.role is Role.ADMIN or community_id in principal.communities


class ConsentRequest(BaseModel):
    """Request body to record a community's consent for a set of rights."""

    model_config = ConfigDict(extra="forbid")
    community_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    rights: Annotated[list[Right], Field(min_length=1, max_length=len(Right))]
    policy_version: Annotated[str, Field(pattern=POLICY_VERSION)] = "v1"


class ConsentResponse(BaseModel):
    """A consent record as the API returns it."""

    id: str
    community_id: str
    rights: list[Right]
    policy_version: str
    revoked: bool


class RevokeResponse(BaseModel):
    """What a revocation changed: recordings revoked and jobs stopped."""

    consent_id: str
    recordings_revoked: int
    jobs_stopped: int


def _view(consent: Consent) -> ConsentResponse:
    return ConsentResponse(
        id=consent.id,
        community_id=consent.community_id,
        rights=sorted(consent.rights),
        policy_version=consent.policy_version,
        revoked=consent.revoked,
    )


def _audit(session: Session, ctx: AdminContext, action: str, consent_id: str) -> None:
    AuditRepository(session).record(ctx.entry(action, f"consent:{consent_id}"))


@router.get("")
def list_consents(
    ctx: Ctx, community_id: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
) -> list[ConsentResponse]:
    if not _may_manage(ctx.admin, community_id):
        raise NOT_PERMITTED
    with ctx.factory() as session:
        return [_view(c) for c in ConsentRepository(session).for_communities([community_id])]


@router.post("", status_code=201)
def create_consent(body: ConsentRequest, ctx: Ctx) -> ConsentResponse:
    if not _may_manage(ctx.admin, body.community_id):
        raise NOT_PERMITTED
    consent = Consent(
        id=f"consent-{uuid4().hex[:16]}",
        community_id=body.community_id,
        rights=frozenset(body.rights),
        policy_version=body.policy_version,
    )
    with ctx.factory() as session:
        ConsentRepository(session).add(consent)
        _audit(session, ctx, "consent:create", consent.id)
    return _view(consent)


@router.get("/{consent_id}")
def get_consent(consent_id: Annotated[str, ConsentId], ctx: Ctx) -> ConsentResponse:
    with ctx.factory() as session:
        consent = ConsentRepository(session).get(consent_id)
    if consent is None or not _may_manage(ctx.admin, consent.community_id):
        raise NOT_FOUND
    return _view(consent)


@router.post("/{consent_id}/revoke")
def revoke(consent_id: Annotated[str, ConsentId], ctx: Ctx) -> RevokeResponse:
    with ctx.factory() as session:
        existing = ConsentRepository(session).get(consent_id)
        if existing is None or not _may_manage(ctx.admin, existing.community_id):
            raise NOT_FOUND
        result = revoke_consent(session, consent_id)
        if result is None:
            raise NOT_FOUND
        _audit(session, ctx, "consent:revoke", consent_id)
    return RevokeResponse(
        consent_id=consent_id,
        recordings_revoked=result.recordings,
        jobs_stopped=result.jobs_stopped,
    )
