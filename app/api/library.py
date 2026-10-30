"""The Library: browse and search what the signed-in user may read, in the language they choose.

Open to every signed-in user, whether or not they belong to a community. What they get back is
filtered by the eligibility gate (their own communities plus public recordings), so a recording
that is private, unpublished, revoked or no longer consented never appears.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import SessionFactory, current_principal, get_session_factory
from app.library import LibraryEntry, browse, search
from app.models.library import LibraryFilter, LibraryView
from app.models.records import HeritageKind
from app.security.permissions import Principal, authorize
from app.security.roles import Action

router = APIRouter(prefix="/v1/library", tags=["library"])
MAX_LIMIT = 50


class LibraryQuery(BaseModel):
    """What the reader asked for. Every field is optional."""

    model_config = ConfigDict(extra="forbid")
    q: Annotated[str | None, Field(max_length=200)] = None
    language: Annotated[str | None, Field(pattern=r"^[a-z]{2,8}$")] = None
    kind: HeritageKind | None = None
    view: LibraryView = LibraryView.ORIGINAL
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 20


class LibraryItem(BaseModel):
    """One passage with its context. `notices` must be shown with it."""

    evidence_id: str
    recording_id: str
    heritage_kind: str
    language: str
    view: str
    passage: str
    start_s: float
    end_s: float
    notices: list[str]
    community: str | None


class LibraryResponse(BaseModel):
    """The matching passages, best or newest first."""

    items: list[LibraryItem]


def _item(entry: LibraryEntry) -> LibraryItem:
    return LibraryItem(
        evidence_id=entry.evidence_id,
        recording_id=entry.recording_id,
        heritage_kind=entry.heritage_kind,
        language=entry.language,
        view=entry.view,
        passage=entry.passage,
        start_s=entry.start_s,
        end_s=entry.end_s,
        notices=list(entry.notices),
        community=entry.community,
    )


@router.get("")
def library(
    params: Annotated[LibraryQuery, Query()],
    principal: Annotated[Principal, Depends(current_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> LibraryResponse:
    """Search by words when `q` is given, otherwise browse the newest recordings."""
    if not authorize(principal, Action.LIBRARY_VIEW).allowed:
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    where = LibraryFilter(params.language, params.kind, params.view, params.limit)
    with factory() as session:
        found = (
            search(session, principal, params.q, where)
            if params.q
            else browse(session, principal, where)
        )
    return LibraryResponse(items=[_item(e) for e in found])
