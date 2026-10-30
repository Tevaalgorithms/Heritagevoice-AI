from fastapi.testclient import TestClient

from app.api.main import app

client = TestClient(app)


def test_health_is_distinct_from_readiness():
    assert client.get("/health").json() == {"status": "ok", "mode": "scaffold"}
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_query_is_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv("HERITAGEVOICE_DEV_API_TOKEN", raising=False)
    assert client.post("/v1/query", json={"question": "Who?"}).status_code == 503


def test_a_signed_in_user_still_gets_503_when_no_database_is_configured(monkeypatch):
    monkeypatch.setenv("HERITAGEVOICE_DEV_API_TOKEN", "test-only-token")
    assert client.post("/v1/query", json={"question": "Who?"}).status_code == 401
    assert (
        client.post(
            "/v1/query",
            json={"question": "Who?"},
            headers={"Authorization": "Bearer wrong"},
        ).status_code
        == 401
    )
    response = client.post(
        "/v1/query",
        json={"question": "Who?"},
        headers={"Authorization": "Bearer test-only-token"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "unavailable"
