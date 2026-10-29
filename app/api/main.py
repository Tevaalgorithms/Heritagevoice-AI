"""Runnable development API. No live-data query path is enabled in this scaffold."""

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.readiness import run_checks
from app.api.tracing import current_trace_id, install_trace_logging, trace_id_middleware
from app.config import Settings
from app.models.evidence import QueryRequest

app = FastAPI(title="HeritageVoice AI", version="0.1.0")
app.middleware("http")(trace_id_middleware)
install_trace_logging()
bearer = HTTPBearer(auto_error=False)


def require_development_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = Settings().dev_api_token
    if expected is None or not expected.get_secret_value():
        raise HTTPException(status_code=503, detail="Development access is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, expected.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid development credentials")


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "mode": "scaffold"}


@app.get("/ready")
def ready(response: Response) -> dict[str, object]:
    """Infrastructure readiness only. `/query` stays closed until the agents are implemented."""
    is_ready, checks = run_checks(Settings())
    response.status_code = 200 if is_ready else 503
    return {"ready": is_ready, "checks": checks}


@app.post("/query", dependencies=[Depends(require_development_token)])
def query(payload: QueryRequest) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "request_id": current_trace_id(),
            "message": "Agent integrations are not implemented. See the implementation backlog.",
        },
    )
