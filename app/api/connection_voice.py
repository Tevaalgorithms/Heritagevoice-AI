"""Search Connections by voice: a few spoken words come back as text for the search box.

Open to signed-in readers and to visitors, because searching the open Connections needs no account.
Each call costs a transcription, so both are rate limited: a signed-in reader per person, a visitor
per address, and visitors together. The audio is deleted as soon as it has been understood and
nothing about it is kept.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_principal
from app.api.public import NO_KEEPING, visitor_key
from app.api.recordings import get_audio_store, rules_from_settings
from app.audio import UploadError
from app.config import Settings
from app.errors import ProviderError
from app.ports import AudioStore
from app.ratelimit import SlidingWindowLimiter
from app.security.permissions import Principal, authorize
from app.security.roles import Action
from app.voice_correction import Spoken
from app.voice_search import SearchVoiceDeps, hear, short_rules
from app.voice_setup import build_search_voice_deps

router = APIRouter(tags=["connections"])
READER_PER_MINUTE = 6
VISITOR_PER_MINUTE = 3
ALL_VISITORS_PER_MINUTE = 20
DEADLINE_S = 60.0
_READERS = SlidingWindowLimiter(READER_PER_MINUTE, 60.0)
_VISITORS = SlidingWindowLimiter(VISITOR_PER_MINUTE, 60.0)
_ALL_VISITORS = SlidingWindowLimiter(ALL_VISITORS_PER_MINUTE, 60.0)
EVERYONE = "all-visitors"


class SpokenSearch(BaseModel):
    """The multipart form: a short recording and the language it is in."""

    model_config = ConfigDict(extra="forbid")
    file: UploadFile
    language: Annotated[str, Field(pattern=r"^[a-z]{2,8}$")]


class Heard(BaseModel):
    """The words that were said; empty if nothing could be made out."""

    heard: str


def get_search_voice_deps(
    store: Annotated[AudioStore, Depends(get_audio_store)],
) -> SearchVoiceDeps:
    settings = Settings()
    deps = build_search_voice_deps(settings, store, rules_from_settings(settings))
    if deps is None:
        raise HTTPException(status_code=503, detail={"code": "voice_unavailable"})
    return deps


def _problem(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def _refuse(limiter: SlidingWindowLimiter, key: str) -> None:
    if not limiter.allow(key):
        retry = str(limiter.retry_after(key))
        raise HTTPException(
            status_code=429, detail={"code": "rate_limited"}, headers={"Retry-After": retry}
        )


async def _heard(form: SpokenSearch, deps: SearchVoiceDeps) -> Heard:
    spoken = Spoken(await form.file.read(short_rules(deps.rules).max_bytes + 1), form.language)
    try:
        work = run_in_threadpool(hear, spoken, deps)
        return Heard(heard=await asyncio.wait_for(work, DEADLINE_S))
    except UploadError as error:
        raise _problem(error.code, error.status_code) from error
    except ProviderError as error:
        raise _problem("voice_failed", 502) from error
    except TimeoutError as error:
        raise _problem("deadline", 504) from error


@router.post("/v1/connections/voice")
async def reader_voice(
    form: Annotated[SpokenSearch, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    deps: Annotated[SearchVoiceDeps, Depends(get_search_voice_deps)],
) -> Heard:
    """A signed-in reader speaks a name or idea to look for."""
    if not authorize(principal, Action.LIBRARY_VIEW).allowed:
        raise _problem("forbidden", 403)
    _refuse(_READERS, principal.user_id)
    return await _heard(form, deps)


@router.post("/v1/public/connections/voice")
async def visitor_voice(
    form: Annotated[SpokenSearch, Form()],
    request: Request,
    response: Response,
    deps: Annotated[SearchVoiceDeps, Depends(get_search_voice_deps)],
) -> Heard:
    """A visitor speaks a name or idea to look for. No sign-in; strictly limited."""
    response.headers.update(NO_KEEPING)
    _refuse(_ALL_VISITORS, EVERYONE)
    _refuse(_VISITORS, visitor_key(request))
    return await _heard(form, deps)
