import json

import httpx
import pytest

from frontend.api_client import ApiClient, ApiRequestError, ModelParamsSpec, NewModelSpec
from frontend.messages import PROBE_MESSAGES, message_for, probe_message

PARAMS = ModelParamsSpec(provider="anthropic", model="claude-haiku-5-5", temperature=0.2)
VIEW = {
    "role": "translation",
    "provider": "anthropic",
    "model": "claude-haiku-5-5",
    "temperature": 0.2,
    "timeout_s": 30.0,
    "max_retries": 2,
    "source": "database",
}


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_me_tells_the_ui_the_role():
    def handler(request):
        assert request.url.path == "/v1/me"
        return httpx.Response(200, json={"user_id": "u1", "role": "admin", "communities": []})

    assert client_for(handler).me().role == "admin"


CATALOG = [
    {
        "model_id": "claude-haiku-5-5",
        "provider": "anthropic",
        "key_name": "HERITAGEVOICE_LLM_API_KEY",
        "status": "active",
        "key_configured": True,
    }
]


def test_the_overview_is_parsed_and_carries_no_key_value():
    def handler(request):
        return httpx.Response(
            200,
            json={"catalog": CATALOG, "roles": [{**VIEW, "source": "default", "fallbacks": []}]},
        )

    overview = client_for(handler).model_settings()
    assert overview.catalog[0].key_configured is True
    assert overview.catalog[0].key_name == "HERITAGEVOICE_LLM_API_KEY"
    assert overview.roles[0].source == "default"
    assert overview.roles[0].fallbacks == []


def test_adding_a_model_and_changing_its_status_use_the_catalogue_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.read()))
        return httpx.Response(200, json=CATALOG[0])

    client = client_for(handler)
    client.add_model(NewModelSpec(model_id="m-1", provider="anthropic", key_name="SOME_KEY"))
    client.set_model_status("m-1", "disabled")
    assert [(m, p) for m, p, _ in seen] == [
        ("POST", "/admin/models/catalog"),
        ("PUT", "/admin/models/catalog/m-1"),
    ]
    assert b"SOME_KEY" in seen[0][2]
    assert b'"disabled"' in seen[1][2]


def test_saving_sends_the_fallbacks_in_order():
    seen = {}

    def handler(request):
        seen["body"] = request.read()
        return httpx.Response(200, json=VIEW)

    params = ModelParamsSpec(provider="anthropic", model="a", fallbacks=["b", "c"])
    client_for(handler).save_model_setting("translation", params)
    assert b'"fallbacks":["b","c"]' in seen["body"].replace(b" ", b"")


def test_saving_sends_only_model_parameters_never_a_key():
    seen = {}

    def handler(request):
        seen["method"], seen["path"], seen["body"] = (
            request.method,
            request.url.path,
            request.read(),
        )
        return httpx.Response(200, json=VIEW)

    result = client_for(handler).save_model_setting("translation", PARAMS)
    assert (seen["method"], seen["path"]) == ("PUT", "/admin/models/translation")
    assert b"api_key" not in seen["body"]
    assert b"key" not in seen["body"].lower()
    assert result.model == "claude-haiku-5-5"


def test_reset_and_probe_use_their_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/test"):
            return httpx.Response(200, json={"ok": False, "code": "bad_key"})
        return httpx.Response(200, json={**VIEW, "source": "default"})

    client = client_for(handler)
    assert client.reset_model_setting("translation").source == "default"
    probe = client.probe_model_setting("translation", PARAMS)
    assert (probe.ok, probe.code) == (False, "bad_key")
    assert seen == [
        ("DELETE", "/admin/models/translation"),
        ("POST", "/admin/models/translation/test"),
    ]


@pytest.mark.parametrize("code", sorted(PROBE_MESSAGES))
def test_every_probe_code_has_a_plain_message(code):
    assert probe_message(code) == PROBE_MESSAGES[code]


def test_unknown_probe_codes_get_a_generic_message():
    assert probe_message("surprise") == "The test failed."
    assert probe_message(None) == "The test failed."


def test_non_admins_get_a_clear_refusal():
    def handler(request):
        return httpx.Response(403, json={"detail": "Not permitted"})

    with pytest.raises(ApiRequestError) as error:
        client_for(handler).model_settings()
    assert error.value.status_code == 403
    assert "not allowed" in message_for(error.value)


def test_a_model_chosen_twice_for_one_job_is_caught_before_sending():
    from frontend.views.settings import _repeated  # noqa: PLC0415

    twice = ModelParamsSpec(
        provider="anthropic",
        model="claude-haiku-5-5",
        fallbacks=["gpt-5.4-nano", "claude-sonnet-5-5", "claude-haiku-5-5"],
    )
    assert _repeated(twice) == "claude-haiku-5-5"
    assert _repeated(PARAMS) is None


def test_refused_values_say_which_field_and_why_but_never_the_value():
    body = {
        "detail": [
            {
                "loc": ["body", "fallbacks"],
                "msg": "Value error, a model can appear only once in the chain",
                "input": "secret-value",
            }
        ]
    }
    client = client_for(lambda request: httpx.Response(422, json=body))
    with pytest.raises(ApiRequestError) as error:
        client.model_settings()
    text = message_for(error.value)
    assert "fallbacks: a model can appear only once in the chain" in text
    assert "secret-value" not in text


def test_a_server_failure_gives_a_reference_to_quote():
    handler = lambda request: httpx.Response(500, headers={"x-trace-id": "abc123"})  # noqa: E731
    with pytest.raises(ApiRequestError) as error:
        client_for(handler).model_settings()
    text = message_for(error.value)
    assert "problem on our side" in text
    assert text.endswith("Reference: abc123")


def test_teaches_is_a_relationship_a_reviewer_can_pick_and_read():
    from frontend.relations import RELATIONS, phrase  # noqa: PLC0415

    assert "TEACHES" in RELATIONS
    assert phrase("TEACHES") == "teaches"


def test_a_spoken_correction_is_sent_as_a_form_and_read_back():
    seen = {}

    def handler(request):
        seen["path"], seen["auth"] = request.url.path, request.headers.get("authorization")
        seen["type"] = request.headers.get("content-type", "")
        reply = {
            "heard": "இது பணிவு", "english": "this is humility", "understood": True,
            "subject": "யானை", "relation": "TEACHES", "object": "பணிவு",
        }  # fmt: skip
        return httpx.Response(200, json=reply)

    found = client_for(handler).voice_correction("a1", b"audio", "ta")
    assert seen["path"] == "/v1/graph/assertions/a1/voice"
    assert seen["auth"] == "Bearer tok"
    assert seen["type"].startswith("multipart/form-data")
    assert (found.heard, found.relation, found.understood) == ("இது பணிவு", "TEACHES", True)


def test_the_typed_form_starts_from_the_spoken_correction_when_it_was_understood():
    from frontend.api_models import AssertionView, VoiceSuggestionView  # noqa: PLC0415
    from frontend.views.relationships import _starting_point  # noqa: PLC0415

    item = AssertionView(
        id="a1", recording_id="r1", subject="proverb", relation="DESCRIBES", object="elephant",
        asserted_by="unknown", review_state="pending", confidence=0.4,
    )  # fmt: skip
    clear = VoiceSuggestionView(
        heard="h",
        english="e",
        understood=True,
        subject="proverb",
        relation="TEACHES",
        object="humility",
    )
    unclear = VoiceSuggestionView(heard="h", english="e", understood=False)
    assert _starting_point(item, clear).relation == "TEACHES"
    assert _starting_point(item, clear).object == "humility"
    assert _starting_point(item, unclear) == item
    assert _starting_point(item, None) == item


def test_a_failed_voice_correction_has_its_own_message():
    assert "type the correction" in message_for(ApiRequestError(502, "voice_failed"))


def test_withdrawing_a_recording_posts_the_reason_to_the_revoke_endpoint():
    seen = {}

    def handler(request):
        seen["path"], seen["auth"] = request.url.path, request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"recording_id": "r1", "status": "revoked"})

    client_for(handler).withdraw_recording("r1", "Family asked for it to be removed")
    assert seen["path"] == "/v1/recordings/r1/revoke"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] == {"policy_version": "v1", "reason": "Family asked for it to be removed"}


@pytest.mark.parametrize(
    ("reason", "understood", "allowed"),
    [("", True, False), ("   ", True, False), ("Asked by family", False, False)]
    + [("Asked by family", True, True)],
)
def test_withdrawing_needs_a_reason_and_a_confirmation(reason, understood, allowed):
    from frontend.views.review import can_withdraw  # noqa: PLC0415

    assert can_withdraw(reason, understood) is allowed


def test_the_account_calls_go_to_the_admin_user_endpoints():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.content))
        if request.method == "GET":
            row = {"sub": "s1", "email": "a@example.org", "role": "member", "status": "active"}
            return httpx.Response(200, json=[{**row, "communities": ["c1"], "is_you": True}])
        return httpx.Response(200, json={})

    client = client_for(handler)
    person = client.accounts()[0]
    assert (person.email, person.role, person.is_you, person.communities) == (
        "a@example.org",
        "member",
        True,
        ["c1"],
    )
    client.set_account_role("s1", "reviewer")
    client.set_account_groups("s1", ["c1", "c2"])
    client.disable_account("s1")
    assert [(method, path) for method, path, _ in seen] == [
        ("GET", "/admin/users"),
        ("PUT", "/admin/users/s1/role"),
        ("PUT", "/admin/users/s1/communities"),
        ("POST", "/admin/users/s1/disable"),
    ]
    assert json.loads(seen[1][2]) == {"role": "reviewer"}
    assert json.loads(seen[2][2]) == {"communities": ["c1", "c2"]}


def test_every_role_has_a_label_and_a_one_line_description():
    from frontend.roles import ROLE_CHOICES, ROLE_DESCRIPTIONS, ROLE_LABELS, role_label  # noqa: PLC0415

    assert set(ROLE_LABELS) == set(ROLE_DESCRIPTIONS) == {"member", "reviewer", "admin"}
    assert set(ROLE_CHOICES.values()) == set(ROLE_LABELS)
    assert role_label("reviewer") == "Coordinator"
    assert role_label("surprise") == "surprise"


def test_groups_are_named_and_a_removed_group_shows_its_id():
    from frontend.views.accounts import describe_groups  # noqa: PLC0415

    names = {"c1": "Our Family"}
    assert describe_groups([], names) == "no groups"
    assert describe_groups(["c1", "gone"], names) == "Our Family, gone"
