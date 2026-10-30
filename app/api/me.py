"""Who am I: lets the UI show only the pages the signed-in user may use."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import current_principal
from app.security.permissions import Principal

router = APIRouter(prefix="/v1", tags=["me"])


class Me(BaseModel):
    """The signed-in user as the server knows them: ID, role and communities."""

    user_id: str
    role: str
    communities: list[str]


@router.get("/me")
def me(principal: Annotated[Principal, Depends(current_principal)]) -> Me:
    return Me(
        user_id=principal.user_id, role=principal.role, communities=sorted(principal.communities)
    )
