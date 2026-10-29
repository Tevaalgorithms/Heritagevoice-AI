"""Runnable development API. No live-data query path is enabled in this scaffold."""

import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.models.evidence import QueryRequest

app = FastAPI(title="HeritageVoice AI", version="0.1.0")
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


@app.get("/ready", status_code=503)
def ready() -> dict[str, object]:
    return {
        "ready": False,
        "missing": [
            "trusted_identity_and_thread_ownership",
            "supervisor",
            "hybrid_rag",
            "graph_rag",
            "verification_and_synthesis",
            "persistent_memory",
        ],
    }


@app.post("/query", dependencies=[Depends(require_development_token)])
def query(payload: QueryRequest) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "request_id": str(uuid4()),
            "message": "Agent integrations are not implemented. See the implementation backlog.",
        },
    )
