"""The HeritageVoice API: health, records, review, the Library and questions."""

import logging

from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.consents import router as consents_router
from app.api.graph_review import router as graph_review_router
from app.api.graph_voice import router as graph_voice_router
from app.api.group_members import router as group_members_router
from app.api.groups import mine_router as my_groups_router
from app.api.groups import router as groups_router
from app.api.integrations import router as integrations_router
from app.api.library import router as library_router
from app.api.me import router as me_router
from app.api.media import router as media_router
from app.api.model_settings import router as model_settings_router
from app.api.open_sharing import router as open_sharing_router
from app.api.public import router as public_router
from app.api.query import router as query_router
from app.api.readiness import run_checks
from app.api.recordings import router as recordings_router
from app.api.reports import router as reports_router
from app.api.review import router as review_router
from app.api.tracing import install_trace_logging, trace_id_middleware
from app.api.usage import router as usage_router
from app.config import Settings

logger = logging.getLogger("heritagevoice.api")
DENIED_BY_AWS = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}
app = FastAPI(title="HeritageVoice AI", version="0.1.0")
app.middleware("http")(trace_id_middleware)
install_trace_logging()


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    """Say what is wrong and where, but never echo submitted values (they may be secrets)."""
    problems = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in error.errors()]
    return JSONResponse(status_code=422, content={"detail": problems})


@app.exception_handler(ClientError)
def aws_error(request: Request, error: ClientError) -> JSONResponse:
    """An AWS service refused or failed. Log only its short code (the message can name accounts),
    and say which case it is: a missing permission is fixed by applying the infrastructure."""
    code = str(error.response.get("Error", {}).get("Code", "unknown"))
    logger.error("AWS call failed (%s) on %s %s", code, request.method, request.url.path)
    problem = "permission_missing" if code in DENIED_BY_AWS else "aws_error"
    return JSONResponse(status_code=502, content={"detail": {"code": problem}})


app.include_router(admin_router)
app.include_router(consents_router)
app.include_router(groups_router)
app.include_router(group_members_router)
app.include_router(graph_review_router)
app.include_router(media_router)
app.include_router(open_sharing_router)
app.include_router(graph_voice_router)
app.include_router(reports_router)
app.include_router(usage_router)
app.include_router(my_groups_router)
app.include_router(integrations_router)
app.include_router(library_router)
app.include_router(model_settings_router)
app.include_router(me_router)
app.include_router(recordings_router)
app.include_router(public_router)
app.include_router(query_router)
app.include_router(review_router)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "mode": "scaffold"}


@app.get("/ready")
def ready(response: Response) -> dict[str, object]:
    """Infrastructure readiness: each configured dependency, not the agents."""
    is_ready, checks = run_checks(Settings())
    response.status_code = 200 if is_ready else 503
    return {"ready": is_ready, "checks": checks}
