"""People in a group. An admin, or a coordinator of that group, adds and removes them.

The coordinator types the person's email; nobody has to create the family themselves. Only people
who already have an approved account can be added, and no list of everyone's emails is ever shown:
a coordinator sees the members of their own groups only. Changes are audit-logged by account ID.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.admin import SUB, AdminContext, Identity, context_for
from app.db.repositories import AuditRepository, CommunityRepository, UserRepository
from app.models.groups import OPEN_COMMUNITY
from app.models.users import UserStatus
from app.security.roles import Action, Role

router = APIRouter(prefix="/admin/groups/{group_id}/members", tags=["admin"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.GROUP_MANAGE))]
GroupId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
UNKNOWN_EMAIL = "(no longer in the identity service)"


class MemberView(BaseModel):
    """A member of the group."""

    sub: str
    email: str


class AddMember(BaseModel):
    """The email address of an existing, approved account."""

    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s\"\\]+@[^@\s\"\\]+\.[^@\s\"\\]+$", max_length=254)


def _problem(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def _managed(ctx: AdminContext, session: Session, group_id: str) -> None:
    """404 unless this group exists and the caller may manage it (a coordinator: their own)."""
    mine = ctx.admin.role is Role.ADMIN or group_id in ctx.admin.communities
    exists = bool(CommunityRepository(session).among([group_id]))
    if group_id == OPEN_COMMUNITY or not (mine and exists):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
def list_members(group_id: GroupId, ctx: Ctx, identity: Identity) -> list[MemberView]:
    with ctx.factory() as session:
        _managed(ctx, session, group_id)
        subs = UserRepository(session).members_of(group_id)
    return [MemberView(sub=sub, email=identity.email_of(sub) or UNKNOWN_EMAIL) for sub in subs]


@router.post("", status_code=201)
def add_member(group_id: GroupId, body: AddMember, ctx: Ctx, identity: Identity) -> MemberView:
    sub = identity.find_sub(body.email.strip())
    if sub is None:
        raise _problem("not_signed_up", 404)
    with ctx.factory() as session:
        _managed(ctx, session, group_id)
        users = UserRepository(session)
        user = users.get(sub)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise _problem("not_approved", 404)
        users.add_community(sub, group_id)
        AuditRepository(session).record(ctx.entry("group:add_member", f"group:{group_id}", sub))
    return MemberView(sub=sub, email=body.email.strip())


@router.delete("/{sub}")
def remove_member(
    group_id: GroupId, sub: Annotated[str, Path(pattern=SUB.metadata[0].pattern)], ctx: Ctx
) -> dict[str, str]:
    with ctx.factory() as session:
        _managed(ctx, session, group_id)
        users = UserRepository(session)
        user = users.get(sub)
        if user is None or group_id not in user.communities:
            raise HTTPException(status_code=404, detail="Not found")
        users.remove_community(sub, group_id)
        AuditRepository(session).record(ctx.entry("group:remove_member", f"group:{group_id}", sub))
    return {"sub": sub}
