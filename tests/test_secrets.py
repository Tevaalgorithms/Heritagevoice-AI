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
