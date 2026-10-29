"""Runnable development API. No live-data query path is enabled in this scaffold."""

from fastapi import Depends, FastAPI, HTTPException, Response

from app.api.admin import router as admin_router
from app.api.auth import require_action
from app.api.readiness import run_checks
from app.api.recordings import router as recordings_router
from app.api.tracing import current_trace_id, install_trace_logging, trace_id_middleware
from app.config import Settings
from app.models.evidence import QueryRequest
from app.security.roles import Action

app = FastAPI(title="HeritageVoice AI", version="0.1.0")
app.middleware("http")(trace_id_middleware)
install_trace_logging()
app.include_router(admin_router)
app.include_router(recordings_router)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "mode": "scaffold"}


@app.get("/ready")
def ready(response: Response) -> dict[str, object]:
    """Infrastructure readiness only. `/query` stays closed until the agents are implemented."""
    is_ready, checks = run_checks(Settings())
    response.status_code = 200 if is_ready else 503
    return {"ready": is_ready, "checks": checks}


@app.post("/query", dependencies=[Depends(require_action(Action.QUERY_ASK))])
def query(payload: QueryRequest) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "request_id": current_trace_id(),
            "message": "Agent integrations are not implemented. See the implementation backlog.",
        },
    )
