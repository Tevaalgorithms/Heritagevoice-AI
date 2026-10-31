"""Groups: a family, a village, a choir. Admins and coordinators manage them; anyone signed in can
list the groups they belong to, with the consents they can pick when adding a recording.

A coordinator sees and changes only the groups they belong to. Whoever creates a group joins it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from app.api.admin import AdminContext, context_for
from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.db.repositories import (
    AuditRepository,
    CommunityRepository,
    ConsentRepository,
    UserRepository,
)
from app.models.groups import Group
from app.models.records import Right
from app.security.permissions import Principal
from app.security.roles import Action, Role

router = APIRouter(prefix="/admin/groups", tags=["admin"])
mine_router = APIRouter(prefix="/v1/groups", tags=["groups"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.GROUP_MANAGE))]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class GroupRequest(BaseModel):
    """Request body to create a group by its friendly name."""

    name: Name


class ConsentChoice(BaseModel):
    """A consent a contributor can pick: its reference and what it allows."""

    id: str
    policy_version: str
    rights: list[Right]


class MyGroup(BaseModel):
    """A group the signed-in user belongs to, with its active consents."""

    id: str
    name: str
    consents: list[ConsentChoice]


def _visible(principal: Principal, session_groups: CommunityRepository) -> list[Group]:
    if principal.role is Role.ADMIN:
        return session_groups.all()
    return session_groups.among(sorted(principal.communities))


@router.get("")
def list_groups(ctx: Ctx) -> list[Group]:
    with ctx.factory() as session:
        return _visible(ctx.admin, CommunityRepository(session))


@router.post("", status_code=201)
def create_group(body: GroupRequest, ctx: Ctx) -> Group:
    with ctx.factory() as session:
        group = CommunityRepository(session).create(body.name, ctx.admin.user_id)
        UserRepository(session).add_community(ctx.admin.user_id, group.id)
        AuditRepository(session).record(ctx.entry("group:create", f"group:{group.id}"))
    return group


@mine_router.get("/mine")
def my_groups(
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> list[MyGroup]:
    ids = sorted(principal.communities)
    with factory() as session:
        groups = CommunityRepository(session).among(ids)
        consents = ConsentRepository(session).for_communities(ids)
    return [
        MyGroup(
            id=group.id,
            name=group.name,
            consents=[
                ConsentChoice(id=c.id, policy_version=c.policy_version, rights=sorted(c.rights))
                for c in consents
                if c.community_id == group.id and not c.revoked
            ],
        )
        for group in groups
    ]
