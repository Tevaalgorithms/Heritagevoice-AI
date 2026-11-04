"""Correct a proposed relationship by speaking. Admins only, for proposals they may review.

The reviewer's audio is transcribed, translated and interpreted, then thrown away. Nothing is
saved here: the answer is a suggestion the reviewer checks and approves through the normal
decision step. Each call is audit-logged by ID, never with the words or the audio.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Path, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.api.admin import AdminContext, context_for
from app.api.graph_review import NOT_FOUND, passage_for
from app.api.recordings import get_audio_store, rules_from_settings
from app.api.review import allowed_recording
from app.audio import UploadError
from app.config import Settings
from app.db.repositories import AuditRepository, GraphAssertionRepository
from app.errors import ProviderError
from app.models.records import GraphAssertion, Relation, ReviewState
from app.ports import AudioStore
from app.ratelimit import SlidingWindowLimiter
from app.security.roles import Action
from app.voice_correction import Spoken, VoiceDeps, VoiceFix, understand_correction
from app.voice_setup import build_voice_deps

router = APIRouter(prefix="/v1/graph", tags=["graph"])
Ctx = Annotated[AdminContext, Depends(context_for(Action.REVIEW_APPROVE))]
VOICE_PER_MINUTE = 6
VOICE_DEADLINE_S = 120.0
_LIMITER = SlidingWindowLimiter(VOICE_PER_MINUTE, 60.0)


def get_voice_limiter() -> SlidingWindowLimiter:
    return _LIMITER


def get_voice_deps(ctx: Ctx, store: Annotated[AudioStore, Depends(get_audio_store)]) -> VoiceDeps:
    settings = Settings()
    deps = build_voice_deps(settings, ctx.factory, store, rules_from_settings(settings))
    if deps is None:
        raise HTTPException(status_code=503, detail={"code": "voice_unavailable"})
    return deps


class VoiceForm(BaseModel):
    """The multipart form: the spoken correction and the language it is in."""

    model_config = ConfigDict(extra="forbid")
    file: UploadFile
    language: Annotated[str, Field(pattern=r"^[a-z]{2,8}$")]


class VoiceSuggestion(BaseModel):
    """What was heard, in the reviewer's language and in English, and the relationship it means.
    `understood` is false when nothing clear could be made of it."""

    heard: str
    english: str
    understood: bool
    subject: str = ""
    relation: Relation | None = None
    object: str = ""


def _problem(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code})


def _pending(ctx: AdminContext, assertion_id: str) -> tuple[GraphAssertion, str]:
    with ctx.factory() as session:
        assertion = GraphAssertionRepository(session).get(assertion_id)
        if assertion is None:
            raise NOT_FOUND
        allowed_recording(session, ctx.admin, assertion.recording_id, Action.REVIEW_APPROVE)
        if assertion.review_state is not ReviewState.PENDING:
            raise _problem("not_reviewable", 409)
        return assertion, passage_for(session, assertion)


def _suggest(ctx: AdminContext, assertion_id: str, spoken: Spoken, deps: VoiceDeps) -> VoiceFix:
    assertion, passage = _pending(ctx, assertion_id)
    fix = understand_correction(assertion, passage, spoken, deps)
    with ctx.factory() as session:
        AuditRepository(session).record(ctx.entry("graph:voice", f"graph:{assertion_id}"))
    return fix


def _suggestion(fix: VoiceFix) -> VoiceSuggestion:
    found = fix.suggestion
    if found is None:
        return VoiceSuggestion(heard=fix.heard, english=fix.english, understood=False)
    return VoiceSuggestion(
        heard=fix.heard,
        english=fix.english,
        understood=True,
        subject=found.subject,
        relation=found.relation,
        object=found.object,
    )


def throttle_voice(
    ctx: Ctx, limiter: Annotated[SlidingWindowLimiter, Depends(get_voice_limiter)]
) -> None:
    """Refuse an admin who is sending corrections too fast; each one costs a transcription."""
    user_id = ctx.admin.user_id
    if not limiter.allow(user_id):
        retry = str(limiter.retry_after(user_id))
        raise HTTPException(
            status_code=429, detail={"code": "rate_limited"}, headers={"Retry-After": retry}
        )


@router.post("/assertions/{assertion_id}/voice", dependencies=[Depends(throttle_voice)])
async def correct_by_voice(
    assertion_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
    form: Annotated[VoiceForm, Form()],
    ctx: Ctx,
    deps: Annotated[VoiceDeps, Depends(get_voice_deps)],
) -> VoiceSuggestion:
    spoken = Spoken(await form.file.read(deps.rules.max_bytes + 1), form.language)
    try:
        work = run_in_threadpool(_suggest, ctx, assertion_id, spoken, deps)
        return _suggestion(await asyncio.wait_for(work, VOICE_DEADLINE_S))
    except UploadError as error:
        raise _problem(error.code, error.status_code) from error
    except ProviderError as error:
        raise _problem("voice_failed", 502) from error
    except TimeoutError as error:
        raise _problem("deadline", 504) from error
