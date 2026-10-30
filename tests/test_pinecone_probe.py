import pytest
from pydantic import SecretStr

from app.adapters import pinecone_probe
from app.adapters.pinecone_probe import PineconeConnection

KEY = SecretStr("pc-key-123")


class NotFoundException(Exception):  # noqa: N818 - mirrors the Pinecone SDK's exception name
    pass


class UnauthorizedException(Exception):  # noqa: N818 - mirrors the Pinecone SDK's exception name
    pass


class Described:
    def __init__(self, dimension):
        self.dimension = dimension


def fake_pinecone(monkeypatch, result=None, error=None):
    class Client:
        def __init__(self, api_key):
            self.api_key = api_key

        def describe_index(self, name):
            if error is not None:
                raise error
            return result

    monkeypatch.setattr(pinecone_probe, "Pinecone", Client)


def test_without_a_key_or_an_index_nothing_is_called():
    assert PineconeConnection().check(None, "i", 1024).code == "no_key"
    assert PineconeConnection().check(KEY, None, 1024).code == "no_index"
    assert PineconeConnection().check(KEY, "", 1024).code == "no_index"


def test_a_matching_index_is_ok(monkeypatch):
    fake_pinecone(monkeypatch, Described(1024))
    assert PineconeConnection().check(KEY, "idx", 1024).ok is True


def test_an_index_with_the_wrong_dimension_is_reported(monkeypatch):
    fake_pinecone(monkeypatch, Described(768))
    result = PineconeConnection().check(KEY, "idx", 1024)
    assert (result.ok, result.code) == (False, "dimension_mismatch")


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NotFoundException("secret detail"), "unknown_index"),
        (UnauthorizedException("secret detail"), "bad_key"),
        (RuntimeError("secret detail"), "provider_error"),
    ],
)
def test_provider_errors_become_short_codes_without_their_text(monkeypatch, error, code):
    fake_pinecone(monkeypatch, error=error)
    result = PineconeConnection().check(KEY, "idx", 1024)
    assert result.code == code
    assert "secret" not in result.model_dump_json()
