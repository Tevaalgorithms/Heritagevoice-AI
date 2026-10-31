import pytest
from pydantic import SecretStr

from app.adapters import neo4j_probe
from app.adapters.neo4j_probe import Neo4jConnection

PASSWORD = SecretStr("pw-123")
URI = "neo4j+s://abc.databases.neo4j.io"


class AuthError(Exception):
    pass


class ServiceUnavailable(Exception):  # noqa: N818 - mirrors the Neo4j driver's name
    pass


class ConfigurationError(Exception):
    pass


class Driver:
    def __init__(self, error):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def verify_connectivity(self):
        if self.error is not None:
            raise self.error


def fake_driver(monkeypatch, error=None):
    seen = []

    class Database:
        @staticmethod
        def driver(uri, auth):
            seen.append((uri, auth))
            return Driver(error)

    monkeypatch.setattr(neo4j_probe, "GraphDatabase", Database)
    return seen


@pytest.mark.parametrize(
    ("uri", "user", "password"),
    [
        (None, "neo4j", PASSWORD),
        (URI, None, PASSWORD),
        (URI, "neo4j", None),
        ("", "neo4j", PASSWORD),
    ],
)
def test_missing_settings_call_nothing(monkeypatch, uri, user, password):
    seen = fake_driver(monkeypatch)
    assert Neo4jConnection().check(uri, user, password).code == "no_settings"
    assert seen == []


@pytest.mark.parametrize("uri", ["bolt://x", "neo4j://x", "http://x", "neo4j+s:/x"])
def test_only_encrypted_addresses_are_used(monkeypatch, uri):
    seen = fake_driver(monkeypatch)
    assert Neo4jConnection().check(uri, "neo4j", PASSWORD).code == "bad_address"
    assert seen == []


def test_a_working_login_is_ok(monkeypatch):
    seen = fake_driver(monkeypatch)
    assert Neo4jConnection().check(URI, "neo4j", PASSWORD).ok is True
    assert seen == [(URI, ("neo4j", "pw-123"))]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AuthError("secret detail"), "bad_credentials"),
        (ServiceUnavailable("secret detail"), "unreachable"),
        (ConfigurationError("secret detail"), "bad_address"),
        (RuntimeError("secret detail"), "provider_error"),
    ],
)
def test_driver_errors_become_short_codes_without_their_text(monkeypatch, error, code):
    fake_driver(monkeypatch, error)
    result = Neo4jConnection().check(URI, "neo4j", PASSWORD)
    assert result.code == code
    assert "secret" not in result.model_dump_json()
