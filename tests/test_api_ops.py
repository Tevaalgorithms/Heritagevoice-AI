import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.api.tracing import TRACE_HEADER, TraceIdFilter, langsmith_metadata, resolve_trace_id

client = TestClient(app)


def test_every_response_carries_a_trace_id():
    assert len(client.get("/health").headers[TRACE_HEADER]) >= 8


def test_a_safe_incoming_trace_id_is_kept():
    response = client.get("/health", headers={TRACE_HEADER: "abc-12345678"})
    assert response.headers[TRACE_HEADER] == "abc-12345678"


def test_an_unsafe_incoming_trace_id_is_replaced():
    for bad in ("short", "x" * 100, "bad id\nfake log line"):
        assert resolve_trace_id(bad) != bad


def test_trace_id_reaches_logs_and_langsmith_metadata():
    record = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    assert TraceIdFilter().filter(record)
    assert record.trace_id == "-"
    assert langsmith_metadata() == {"trace_id": "-"}


def test_ready_is_503_when_the_database_is_not_configured(monkeypatch):
    monkeypatch.delenv("HERITAGEVOICE_DATABASE_URL", raising=False)
    monkeypatch.setenv("HERITAGEVOICE_AUDIO_BUCKET", "")
    body = client.get("/ready")
    assert body.status_code == 503
    assert body.json()["checks"]["postgres"] == "not_configured"


def test_ready_is_200_when_every_configured_dependency_is_up(monkeypatch, tmp_path):
    monkeypatch.setenv("HERITAGEVOICE_DATABASE_URL", f"sqlite:///{tmp_path / 'r.db'}")
    monkeypatch.delenv("HERITAGEVOICE_AUDIO_BUCKET", raising=False)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": "ok", "audio_bucket": "skipped"}


def test_ready_reports_a_failed_dependency_without_leaking_details(monkeypatch):
    marker = "not-a-real-password"
    monkeypatch.setenv(
        "HERITAGEVOICE_DATABASE_URL", f"postgresql+psycopg://u:{marker}@127.0.0.1:1/x"
    )
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "failed"
    assert marker not in response.text


def test_validation_errors_never_echo_the_submitted_values():
    submitted = uuid4().hex
    body = {"api_key": submitted, "model": submitted}
    response = client.put("/admin/models/translation", json=body)
    assert response.status_code in {401, 403, 422, 503}
    assert submitted not in response.text


def test_a_crash_still_returns_a_trace_id_and_no_error_text(caplog):
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.api.tracing import trace_id_middleware  # noqa: PLC0415

    small = FastAPI()
    small.middleware("http")(trace_id_middleware)

    @small.get("/boom")
    def boom():
        raise RuntimeError("secret detail")

    with caplog.at_level("ERROR", logger="heritagevoice.api"):
        response = TestClient(small, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal"}}
    assert response.headers[TRACE_HEADER]
    assert "secret detail" not in response.text
    assert any("unhandled error on GET /boom" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("aws_code", "expected"),
    [("AccessDeniedException", "permission_missing"), ("ThrottlingException", "aws_error")],
)
def test_an_aws_refusal_becomes_a_clear_502_without_the_aws_text(aws_code, expected, caplog):
    from botocore.exceptions import ClientError  # noqa: PLC0415
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.api.main import aws_error  # noqa: PLC0415

    small = FastAPI()
    small.add_exception_handler(ClientError, aws_error)

    @small.get("/denied")
    def denied():
        message = "User: arn:aws:iam::123456789012:role/x is not authorized"
        raise ClientError({"Error": {"Code": aws_code, "Message": message}}, "ListUsers")

    with caplog.at_level("ERROR", logger="heritagevoice.api"):
        response = TestClient(small, raise_server_exceptions=False).get("/denied")
    assert response.status_code == 502
    assert response.json() == {"detail": {"code": expected}}
    assert "123456789012" not in response.text + caplog.text
