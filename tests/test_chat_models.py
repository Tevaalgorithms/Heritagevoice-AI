"""Chat models per provider are built with fixed addresses and the right options. No network."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from app.adapters.chat_models import (
    OPENAI_BASE_URL,
    STRUCTURED_METHOD,
    ChatOptions,
    chat_model,
)
from app.models.llm import Provider

KEY = SecretStr("not-a-real-key-for-tests")


def options(provider, **extra):
    base = {"model": "m-1", "timeout_s": 30.0, "max_retries": 2, "temperature": 0.3}
    return ChatOptions(provider, **{**base, **extra})


def test_anthropic_gets_its_model_timeout_retries_and_temperature():
    model = chat_model(options(Provider.ANTHROPIC), KEY)
    assert isinstance(model, ChatAnthropic)
    assert (model.model, model.temperature, model.max_retries) == ("m-1", 0.3, 2)


def test_openai_uses_the_fixed_public_address_whatever_else_is_configured():
    model = chat_model(options(Provider.OPENAI), KEY)
    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == OPENAI_BASE_URL
    assert OPENAI_BASE_URL == "https://api.openai.com/v1"


def test_openai_is_not_sent_a_temperature_that_newer_models_reject():
    model = chat_model(options(Provider.OPENAI, temperature=0.0), KEY)
    assert model.temperature is None


def test_a_token_limit_is_passed_in_the_form_each_provider_expects():
    assert chat_model(options(Provider.ANTHROPIC, max_tokens=16), KEY).max_tokens == 16
    assert chat_model(options(Provider.OPENAI, max_tokens=16), KEY).max_tokens == 16


def test_the_key_is_never_part_of_the_models_text_form():
    for provider in Provider:
        assert KEY.get_secret_value() not in repr(chat_model(options(provider), KEY))


def test_every_provider_has_a_builder_and_a_structured_output_method():
    assert set(STRUCTURED_METHOD) == set(Provider)
    for provider in Provider:
        assert chat_model(options(provider), KEY) is not None


class Shape(BaseModel):
    answer: str


@pytest.mark.parametrize("provider", list(Provider))
def test_a_structured_chain_can_be_built_for_each_provider(provider):
    from app.adapters.chat_models import structured  # noqa: PLC0415

    assert structured(chat_model(options(provider), KEY), Shape, provider) is not None
