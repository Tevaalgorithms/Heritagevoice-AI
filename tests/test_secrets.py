import logging
import secrets

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import Settings
from app.secrets import (
    FOUND_TTL_S,
    MISSING_TTL_S,
    ParameterStoreSecrets,
    SecretsConfig,
    secrets_for,
)

PATH = "/heritagevoice/prod"


def not_found():
    return ClientError({"Error": {"Code": "ParameterNotFound", "Message": "x"}}, "GetParameter")


class FakeSsm:
    def __init__(self, **values):
        self.values, self.calls, self.error = values, [], None

    def get_parameter(self, Name, WithDecryption):  # noqa: N803 - boto3 parameter names
        self.calls.append((Name, WithDecryption))
        if self.error is not None:
            raise self.error
        key = Name.rsplit("/", 1)[1]
        if key not in self.values:
            raise not_found()
        return {"Parameter": {"Value": self.values[key]}}


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def reader(ssm, environ=None, path=PATH, clock=None):
    config = SecretsConfig(path=path, client=ssm, environ=environ or {}, clock=clock or Clock())
    return ParameterStoreSecrets(config)


def test_a_value_is_read_decrypted_from_the_path_by_name():
    value = secrets.token_hex(6)
    ssm = FakeSsm(MY_KEY=value)
    assert reader(ssm).get("MY_KEY").get_secret_value() == value
    assert ssm.calls == [(f"{PATH}/MY_KEY", True)]


def test_a_value_is_cached_then_refreshed_so_rotation_needs_no_restart():
    clock, ssm = Clock(), FakeSsm(MY_KEY="old")
    secret = reader(ssm, clock=clock)
    assert secret.get("MY_KEY").get_secret_value() == "old"
    ssm.values["MY_KEY"] = "new"
    assert secret.get("MY_KEY").get_secret_value() == "old"  # still cached
    assert len(ssm.calls) == 1
    clock.now = FOUND_TTL_S + 1
    assert secret.get("MY_KEY").get_secret_value() == "new"


def test_a_missing_key_is_retried_soon_so_adding_one_works_quickly():
    clock, ssm = Clock(), FakeSsm()
    secret = reader(ssm, clock=clock)
    assert secret.get("MY_KEY") is None
    assert secret.is_configured("MY_KEY") is False
    assert len(ssm.calls) == 1  # the miss is cached briefly
    ssm.values["MY_KEY"] = "added"
    clock.now = MISSING_TTL_S + 1
    assert secret.is_configured("MY_KEY") is True


def test_the_environment_is_the_fallback_when_the_store_has_no_value():
    assert reader(FakeSsm(), {"MY_KEY": "from-env"}).get("MY_KEY").get_secret_value() == "from-env"


def test_the_store_wins_over_the_environment():
    ssm = FakeSsm(MY_KEY="from-store")
    assert reader(ssm, {"MY_KEY": "from-env"}).get("MY_KEY").get_secret_value() == "from-store"


def test_with_no_store_configured_only_the_environment_is_used():
    ssm = FakeSsm(MY_KEY="never-read")
    secret = reader(ssm, {"MY_KEY": "local"}, path=None)
    assert secret.get("MY_KEY").get_secret_value() == "local"
    assert ssm.calls == []


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetParameter"),
        EndpointConnectionError(endpoint_url="https://ssm.example"),
    ],
    ids=["denied", "unreachable"],
)
def test_a_store_failure_falls_back_to_the_environment_and_logs_no_value(error, caplog):
    ssm = FakeSsm(MY_KEY="unused")
    ssm.error = error
    with caplog.at_level(logging.WARNING, logger="heritagevoice.secrets"):
        result = reader(ssm, {"MY_KEY": "from-env"}).get("MY_KEY")
    assert result.get_secret_value() == "from-env"
    assert "from-env" not in caplog.text
    assert "parameter store" in caplog.text


def test_the_value_is_never_shown_by_repr():
    secret = reader(FakeSsm(MY_KEY="hunter2")).get("MY_KEY")
    assert "hunter2" not in repr(secret)
    assert "hunter2" not in str(secret)


def test_the_reader_is_built_from_the_settings_path():
    settings = Settings(_env_file=None, ssm_path="/heritagevoice/prod/")
    assert isinstance(secrets_for(settings), ParameterStoreSecrets)


# --- writing -------------------------------------------------------------------------------


class RecordingSsm:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def put_parameter(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def writer(ssm, path="/heritagevoice/prod"):
    from app.secrets import ParameterStoreWriter  # noqa: PLC0415

    return ParameterStoreWriter(path, client=ssm)


def test_a_secret_is_written_encrypted_with_the_sites_key_and_overwrites():
    ssm = RecordingSsm()
    writer(ssm).put("OPENAI_API_KEY", "value-123", secret=True)
    assert ssm.calls == [
        {
            "Name": "/heritagevoice/prod/OPENAI_API_KEY",
            "Value": "value-123",
            "Type": "SecureString",
            "Overwrite": True,
            "KeyId": "alias/heritagevoice-prod",
        }
    ]


def test_a_plain_setting_is_written_as_text_without_a_key():
    ssm = RecordingSsm()
    writer(ssm).put("PINECONE_INDEX", "heritage", secret=False)
    (call,) = ssm.calls
    assert call["Type"] == "String"
    assert "KeyId" not in call


def test_the_encryption_key_follows_the_environment_in_the_path():
    ssm = RecordingSsm()
    writer(ssm, "/heritagevoice/staging/").put("OPENAI_API_KEY", "v", secret=True)
    assert ssm.calls[0]["KeyId"] == "alias/heritagevoice-staging"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "Put"),
            "write_denied",
        ),
        (
            ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Put"),
            "write_failed",
        ),
        (EndpointConnectionError(endpoint_url="https://ssm.example"), "write_failed"),
    ],
    ids=["denied", "throttled", "unreachable"],
)
def test_a_failed_write_becomes_a_short_code_that_never_carries_the_value(error, code, caplog):
    from app.secrets import SecretWriteError  # noqa: PLC0415

    with (
        caplog.at_level(logging.WARNING, logger="heritagevoice.secrets"),
        pytest.raises(SecretWriteError) as raised,
    ):
        writer(RecordingSsm(error)).put("OPENAI_API_KEY", "super-secret-value", secret=True)
    assert raised.value.code == code
    assert "super-secret-value" not in caplog.text
    assert "super-secret-value" not in str(raised.value)


def test_without_a_path_nothing_can_be_written():
    from app.secrets import SecretWriteError  # noqa: PLC0415

    with pytest.raises(SecretWriteError) as raised:
        writer(RecordingSsm(), path=None).put("X_API_KEY", "v", secret=True)
    assert raised.value.code == "not_configured"


def test_forgetting_a_name_makes_the_next_read_fetch_it_again():
    clock, ssm = Clock(), FakeSsm(MY_KEY="old")
    secret = reader(ssm, clock=clock)
    assert secret.get("MY_KEY").get_secret_value() == "old"
    ssm.values["MY_KEY"] = "new"
    secret.forget("MY_KEY")
    assert secret.get("MY_KEY").get_secret_value() == "new"


def test_one_reader_is_shared_per_process_so_the_cache_actually_helps():
    from app.secrets import secrets_for  # noqa: PLC0415

    settings = Settings(_env_file=None, ssm_path="/heritagevoice/prod")
    assert secrets_for(settings) is secrets_for(settings)
