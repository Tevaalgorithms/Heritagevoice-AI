"""Connections: the relationships between people, places, songs and customs that people have
reviewed and approved, each with the passage that says it. Open to every signed-in user; what comes
back is filtered by the same gate as search. Visitors have a smaller, rate-limited copy in
`app/api/public.py`."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.connections import Connection, find_connections
from app.models.credit import Credit
from app.models.records import Relation
from app.security.permissions import Principal, authorize
from app.security.roles import Action

router = APIRouter(prefix="/v1/connections", tags=["connections"])
MAX_LIMIT = 50


class ConnectionQuery(BaseModel):
    """What the reader asked for: a name or idea to look for, or nothing for the newest."""

    model_config = ConfigDict(extra="forbid")
    q: Annotated[str | None, Field(max_length=100)] = None
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 20


class ConnectionItem(BaseModel):
    """One relationship and its source. `notices` must be shown with the passage."""

    assertion_id: str
    subject: str
    relation: Relation
    object: str
    recording_id: str
    evidence_id: str
    passage: str
    start_s: float
    end_s: float
    notices: list[str]
    heritage_kind: str = ""
    language: str = ""
    added: str = ""
    credit: Credit | None = None


class ConnectionsResponse(BaseModel):
    """The matching relationships."""

    items: list[ConnectionItem]


def item_of(found: Connection) -> ConnectionItem:
    origin = found.origin
    return ConnectionItem(
        assertion_id=found.assertion_id,
        subject=found.subject,
        relation=found.relation,
        object=found.object,
        recording_id=found.recording_id,
        evidence_id=found.evidence_id,
        passage=found.passage,
        start_s=found.start_s,
        end_s=found.end_s,
        notices=list(found.notices),
        heritage_kind=origin.heritage_kind if origin else "",
        language=origin.language if origin else "",
        added=origin.added if origin else "",
        credit=origin.credit if origin else None,
    )


@router.get("")
def connections(
    params: Annotated[ConnectionQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ConnectionsResponse:
    """Approved relationships that name `q`, or the newest, that this reader may see."""
    if not authorize(principal, Action.LIBRARY_VIEW).allowed:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    with factory() as session:
        found = find_connections(session, principal, params.q or "", params.limit)
    return ConnectionsResponse(items=[item_of(f) for f in found])
