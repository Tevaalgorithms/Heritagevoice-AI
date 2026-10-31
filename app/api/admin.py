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
from app.db.repositories import AuditEntry, AuditRepository, UserRepository
from app.models.users import Signup, UserStatus
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
    """The verified admin making a request, with a way to open database sessions."""

    admin: Principal
    factory: SessionFactory

    def entry(self, action: str, target: str, detail: str | None = None) -> AuditEntry:
        return AuditEntry(self.admin.user_id, action, target, current_trace_id(), detail)


def context_for(action: Action) -> Callable[..., AdminContext]:
    """A dependency that requires `action` and bundles the admin with a session factory."""

    def dependency(
        admin: Annotated[Principal, Depends(require_action(action))],
        factory: Annotated[SessionFactory, Depends(get_session_factory)],
    ) -> AdminContext:
        return AdminContext(admin, factory)

    return dependency


Ctx = Annotated[AdminContext, Depends(context_for(Action.USER_MANAGE))]


class InviteRequest(BaseModel):
    """Request body to invite a new user with a role and communities."""

    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    role: Role = Role.MEMBER
    communities: list[Annotated[str, COMMUNITY_ID]] = []


class RoleRequest(BaseModel):
    """Request body to change a user's role."""

    model_config = ConfigDict(extra="forbid")
    role: Role


class CommunitiesRequest(BaseModel):
    """Request body to replace a user's community memberships."""

    model_config = ConfigDict(extra="forbid")
    communities: list[Annotated[str, COMMUNITY_ID]]


def _not_self(admin: Principal, sub: str) -> None:
    if admin.user_id == sub:
        raise HTTPException(status_code=400, detail="You cannot change your own account")


def _audit(session: Session, ctx: AdminContext, action: str, sub: str) -> None:
    AuditRepository(session).record(ctx.entry(action, f"user:{sub}"))


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


class ApproveRequest(BaseModel):
    """Request body to approve a sign-up: the groups they join. None is fine."""

    model_config = ConfigDict(extra="forbid")
    communities: list[Annotated[str, COMMUNITY_ID]] = Field(default_factory=list, max_length=20)


class SignupView(BaseModel):
    """Someone waiting for approval. Email is shown only to admins."""

    sub: str
    email: str
    created: str


def _waiting(ctx: AdminContext, identity: IdentityProvider) -> list[Signup]:
    """Self-created accounts that have no record here yet, oldest first."""
    signups = identity.list_signups()
    with ctx.factory() as session:
        known = UserRepository(session).known([s.sub for s in signups])
    return sorted((s for s in signups if s.sub not in known), key=lambda s: s.created)


@router.get("/signups")
def list_signups(ctx: Ctx, identity: Identity) -> list[SignupView]:
    return [SignupView(**s.model_dump()) for s in _waiting(ctx, identity)]


def _pending(ctx: AdminContext, identity: IdentityProvider, sub: str) -> None:
    if sub not in {s.sub for s in _waiting(ctx, identity)}:
        raise HTTPException(status_code=404, detail="No such request")


@router.post("/signups/{sub}/approve", status_code=201)
def approve_signup(
    sub: Annotated[str, SUB], body: ApproveRequest, ctx: Ctx, identity: Identity
) -> dict[str, list[str]]:
    """Approve as a contributor (member role). Admins are only ever created by an invitation."""
    _pending(ctx, identity, sub)
    identity.set_role(sub, Role.MEMBER)  # first: if this fails, nothing has been granted
    with ctx.factory() as session:
        UserRepository(session).create(sub, Role.MEMBER, frozenset(body.communities))
        _audit(session, ctx, "signup:approve", sub)
    return {"communities": sorted(body.communities)}


@router.post("/signups/{sub}/decline")
def decline_signup(sub: Annotated[str, SUB], ctx: Ctx, identity: Identity) -> dict[str, str]:
    _pending(ctx, identity, sub)
    identity.disable_user(sub)
    with ctx.factory() as session:
        _audit(session, ctx, "signup:decline", sub)
    return {"sub": sub, "status": UserStatus.DISABLED}
