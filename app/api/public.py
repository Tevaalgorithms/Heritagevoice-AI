"""The open Library: anyone can search what communities chose to share publicly. No sign-in.

A visitor is treated as a reader who belongs to no community, so they can only ever see recordings
that are public, published, approved by an admin, and whose consent still allows public sharing:
the same rule the signed-in Library applies to people from other communities. Asking questions,
uploading and everything else still need an account.

Because there is no sign-in, this endpoint is limited: a per-visitor request rate, small result
sizes, and headers that stop browsers, proxies and search engines from keeping what is shown, so a
withdrawn recording disappears at once.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import SessionFactory, get_session_factory
from app.api.connections import ConnectionsResponse, item_of
from app.api.library import LibraryResponse, _item
from app.api.media import audio_response, public_playable
from app.api.recordings import NOT_FOUND, PathId, get_audio_store
from app.connections import find_connections
from app.library import browse, search
from app.models.library import LibraryFilter, LibraryView
from app.models.records import HeritageKind
from app.ports import AudioStore
from app.ratelimit import SlidingWindowLimiter
from app.security.permissions import Principal
from app.security.principal import POLICY_VERSION
from app.security.roles import Role

router = APIRouter(prefix="/v1/public", tags=["public"])
MAX_LIMIT = 20
REQUESTS_PER_MINUTE = 30
MEDIA_PER_MINUTE = 10
ANONYMOUS = Principal(
    user_id="visitor",
    groups=frozenset({"public"}),
    policy_version=POLICY_VERSION,
    role=Role.MEMBER,
    communities=frozenset(),
)
NO_KEEPING = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
_LIMITER = SlidingWindowLimiter(REQUESTS_PER_MINUTE, 60.0)
_MEDIA_LIMITER = SlidingWindowLimiter(MEDIA_PER_MINUTE, 60.0)


def get_limiter() -> SlidingWindowLimiter:
    return _LIMITER


def get_media_limiter() -> SlidingWindowLimiter:
    """Audio costs far more to serve than text, so it has its own, smaller allowance."""
    return _MEDIA_LIMITER


class PublicQuery(BaseModel):
    """What a visitor may ask for. Smaller limits than a signed-in reader's."""

    model_config = ConfigDict(extra="forbid")
    q: Annotated[str | None, Field(max_length=100)] = None
    language: Annotated[str | None, Field(pattern=r"^[a-z]{2,8}$")] = None
    kind: HeritageKind | None = None
    view: LibraryView = LibraryView.ORIGINAL
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 10


def visitor_key(request: Request) -> str:
    """Who is asking, for the rate limit. The API is only reachable through the web server, which
    sets the first X-Forwarded-For entry to the real client address."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _refuse_if_too_often(request: Request, limiter: SlidingWindowLimiter) -> None:
    visitor = visitor_key(request)
    if not limiter.allow(visitor):
        retry = str(limiter.retry_after(visitor))
        raise HTTPException(
            status_code=429, detail={"code": "rate_limited"}, headers={"Retry-After": retry}
        )


def throttle(
    request: Request, limiter: Annotated[SlidingWindowLimiter, Depends(get_limiter)]
) -> None:
    """Refuse a visitor who has asked too often. Runs before anything is searched."""
    _refuse_if_too_often(request, limiter)


def throttle_media(
    request: Request, limiter: Annotated[SlidingWindowLimiter, Depends(get_media_limiter)]
) -> None:
    """The same, with the smaller allowance for playing audio."""
    _refuse_if_too_often(request, limiter)


@router.get("/library", dependencies=[Depends(throttle)])
def public_library(
    params: Annotated[PublicQuery, Query()],
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> LibraryResponse:
    """Search by words when `q` is given, otherwise browse the newest public recordings."""
    response.headers.update(NO_KEEPING)
    where = LibraryFilter(params.language, params.kind, params.view, params.limit)
    with factory() as session:
        found = (
            search(session, ANONYMOUS, params.q, where)
            if params.q
            else browse(session, ANONYMOUS, where)
        )
    return LibraryResponse(items=[_item(e) for e in found])


class PublicConnectionQuery(BaseModel):
    """What a visitor may ask for. Smaller limits than a signed-in reader's."""

    model_config = ConfigDict(extra="forbid")
    q: Annotated[str | None, Field(max_length=100)] = None
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 10


@router.get("/connections", dependencies=[Depends(throttle)])
def public_connections(
    params: Annotated[PublicConnectionQuery, Query()],
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ConnectionsResponse:
    """Approved relationships from public recordings only, for someone without an account."""
    response.headers.update(NO_KEEPING)
    with factory() as session:
        found = find_connections(session, ANONYMOUS, params.q or "", params.limit)
    return ConnectionsResponse(items=[item_of(f) for f in found])


@router.get("/recordings/{recording_id}/media", dependencies=[Depends(throttle_media)])
def public_media(
    recording_id: Annotated[str, PathId],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> Response:
    """Play a recording that its community shared publicly. Anything else is simply not found, so
    a visitor cannot tell a private recording from one that does not exist."""
    with factory() as session:
        recording = public_playable(session, recording_id)
    if recording is None:
        raise NOT_FOUND
    return audio_response(store, recording, NO_KEEPING)
