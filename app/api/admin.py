"""Admin endpoints: manage users and their community membership. Admin role only.

Database changes commit before the identity service is called, so a disabled or demoted user is
blocked immediately even if the identity call then fails. Every change is audit-logged with the
actor and trace ID, never with content.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.adapters.cognito import CognitoIdentityProvider
from app.api.auth import SessionFactory, get_session_factory, require_action
from app.api.tracing import current_trace_id
from app.config import Settings
from app.db.repositories import AuditRepository, UserRepository
from app.models.users import UserStatus
from app.ports import IdentityProvider
from app.security.permissions import Principal
from app.security.roles import Action, Role

COMMUNITY_ID = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
SUB = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")

router = APIRouter(prefix="/admin", tags=["admin"])


def get_identity_provider() -> IdentityProvider:
    settings = Settings()
    region, pool = settings.cognito_region, settings.cognito_user_pool_id
    if not (region and pool):
        raise HTTPException(status_code=503, detail="Identity service is not configured")
    return CognitoIdentityProvider(region, pool)


Identity = Annotated[IdentityProvider, Depends(get_identity_provider)]


@dataclass(frozen=True)
class AdminContext:
    admin: Principal
    factory: SessionFactory


def admin_context(
    admin: Annotated[Principal, Depends(require_action(Action.USER_MANAGE))],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> AdminContext:
    return AdminContext(admin, factory)


Ctx = Annotated[AdminContext, Depends(admin_context)]


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    role: Role = Role.MEMBER
    communities: list[Annotated[str, COMMUNITY_ID]] = []


class RoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class CommunitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    communities: list[Annotated[str, COMMUNITY_ID]]


def _not_self(admin: Principal, sub: str) -> None:
    if admin.user_id == sub:
        raise HTTPException(status_code=400, detail="You cannot change your own account")


def _audit(session: Session, ctx: AdminContext, action: str, sub: str) -> None:
    AuditRepository(session).record(ctx.admin.user_id, action, f"user:{sub}", current_trace_id())


def _update(session: Session, sub: str, change: Callable[[UserRepository], None]) -> None:
    try:
        change(UserRepository(session))
    except KeyError as error:
        raise HTTPException(status_code=404, detail="User not found") from error


@router.post("/users", status_code=201)
def invite_user(body: InviteRequest, ctx: Ctx, identity: Identity) -> dict[str, str]:
    sub = identity.invite_user(body.email, body.role)
    with ctx.factory() as session:
        UserRepository(session).create(sub, body.role, frozenset(body.communities))
        _audit(session, ctx, "user:invite", sub)
    return {"sub": sub}


@router.put("/users/{sub}/role")
def set_role(
    sub: Annotated[str, SUB], body: RoleRequest, ctx: Ctx, identity: Identity
) -> dict[str, str]:
    _not_self(ctx.admin, sub)
    with ctx.factory() as session:
        _update(session, sub, lambda users: users.set_role(sub, body.role))
        _audit(session, ctx, f"user:role:{body.role}", sub)
    identity.set_role(sub, body.role)
    return {"sub": sub, "role": body.role}


@router.put("/users/{sub}/communities")
def set_communities(
    sub: Annotated[str, SUB], body: CommunitiesRequest, ctx: Ctx
) -> dict[str, list[str]]:
    with ctx.factory() as session:
        _update(session, sub, lambda users: users.set_communities(sub, frozenset(body.communities)))
        _audit(session, ctx, "user:communities", sub)
    return {"communities": sorted(body.communities)}


@router.post("/users/{sub}/disable")
def disable_user(sub: Annotated[str, SUB], ctx: Ctx, identity: Identity) -> dict[str, str]:
    _not_self(ctx.admin, sub)
    with ctx.factory() as session:
        _update(session, sub, lambda users: users.set_status(sub, UserStatus.DISABLED))
        _audit(session, ctx, "user:disable", sub)
    identity.disable_user(sub)
    return {"sub": sub, "status": UserStatus.DISABLED}
