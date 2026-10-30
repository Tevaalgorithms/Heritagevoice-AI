import httpx
import pytest

from frontend.api_client import ApiClient, IntegrationGroup, IntegrationItem
from frontend.messages import CODE_MESSAGES, PROBE_MESSAGES
from frontend.views.integrations import _is_ready, _state, _status


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def item(name="OPENAI_API_KEY", kind="secret", configured=False, **extra):
    fields = {"label": name, "help": "h", "default": None, "planned": False, "value": None}
    return IntegrationItem(name=name, kind=kind, configured=configured, **{**fields, **extra})


def test_a_key_is_sent_once_to_its_own_endpoint_and_the_reply_carries_no_value():
    seen = {}

    def handler(request):
        seen["call"] = (request.method, request.url.path, request.read())
        return httpx.Response(
            200,
            json={
                "name": "OPENAI_API_KEY",
                "label": "OpenAI",
                "kind": "secret",
                "help": "h",
                "configured": True,
                "value": None,
                "default": None,
                "planned": False,
            },
        )

    result = client_for(handler).save_integration("OPENAI_API_KEY", "abc12345")
    assert seen["call"][:2] == ("PUT", "/admin/integrations/OPENAI_API_KEY")
    assert b"abc12345" in seen["call"][2]
    assert result.configured is True
    assert result.value is None
    assert "abc12345" not in result.model_dump_json()


def test_the_overview_is_parsed_into_groups():
    def handler(request):
        body = {"groups": [{"label": "Pinecone", "items": [item().model_dump()]}]}
        return httpx.Response(200, json=body)

    overview = client_for(handler).integrations()
    assert overview.groups[0].label == "Pinecone"
    assert overview.groups[0].items[0].name == "OPENAI_API_KEY"


def test_the_pinecone_test_uses_its_endpoint():
    seen = {}

    def handler(request):
        seen["call"] = (request.method, request.url.path)
        return httpx.Response(200, json={"ok": False, "code": "unknown_index"})

    result = client_for(handler).test_pinecone()
    assert seen["call"] == ("POST", "/admin/integrations/pinecone/test")
    assert (result.ok, result.code) == (False, "unknown_index")


def test_a_service_is_ready_when_every_value_without_a_default_is_set():
    group = IntegrationGroup(
        label="Pinecone",
        items=[
            item("PINECONE_API_KEY", configured=True),
            item("PINECONE_INDEX", "setting", configured=True),
            item("EMBEDDING_MODEL", "setting", default="m"),
        ],
    )
    assert _is_ready(group) is True
    group.items[0] = item("PINECONE_API_KEY", configured=False)
    assert _is_ready(group) is False


def test_language_models_are_ready_with_any_one_providers_key():
    group = IntegrationGroup(
        label="Language models",
        items=[item("HERITAGEVOICE_LLM_API_KEY", configured=True), item("OPENAI_API_KEY")],
    )
    assert _is_ready(group) is True
    assert (
        _is_ready(IntegrationGroup(label="Language models", items=[item("OPENAI_API_KEY")]))
        is False
    )


def test_a_service_that_is_not_built_yet_says_so_instead_of_asking_for_setup():
    group = IntegrationGroup(label="Neo4j", items=[item("NEO4J_PASSWORD", planned=True)])
    assert _state(group)[1] == "not used yet"


def test_each_status_is_plain_words():
    assert _status(item(configured=True)) == "Configured"
    assert _status(item()) == "Missing"
    assert _status(item("EMBEDDING_MODEL", "setting", default="m")) == "Using the default"


@pytest.mark.parametrize(
    "code",
    ["invalid_value", "unknown_integration", "write_denied", "write_failed", "not_configured"],
)
def test_every_error_the_server_can_return_has_a_plain_message(code):
    assert CODE_MESSAGES[code]


@pytest.mark.parametrize(
    "code",
    ["no_key", "no_index", "bad_key", "unknown_index", "dimension_mismatch", "provider_error"],
)
def test_every_pinecone_test_result_has_a_plain_message(code):
    assert PROBE_MESSAGES[code]
