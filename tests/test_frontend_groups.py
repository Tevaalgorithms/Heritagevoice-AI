import httpx

from app.models.records import Right
from frontend.api_client import ApiClient
from frontend.rights import EVERYDAY, RIGHTS, describe


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_every_right_the_server_knows_has_a_plain_label():
    assert set(RIGHTS) == {right.value for right in Right}


def test_public_sharing_is_never_ticked_by_default():
    assert "public_sharing" not in EVERYDAY
    assert set(EVERYDAY) <= set(RIGHTS)


def test_a_consent_is_described_in_plain_words():
    assert describe(["indexing", "translation"]) == "Make it searchable; Let AI translate it"
    assert describe(["unknown"]) == "unknown"


def test_groups_are_listed_and_created_with_the_token():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.headers["authorization"]))
        if request.method == "POST":
            return httpx.Response(201, json={"id": "my-family", "name": "My family"})
        return httpx.Response(200, json=[{"id": "my-family", "name": "My family"}])

    client = client_for(handler)
    assert client.groups()[0].name == "My family"
    assert client.create_group("My family").id == "my-family"
    assert seen == [("GET", "/admin/groups", "Bearer tok"), ("POST", "/admin/groups", "Bearer tok")]


def test_my_groups_carry_their_consents():
    body = [
        {
            "id": "my-family",
            "name": "My family",
            "consents": [{"id": "consent-1", "policy_version": "v1", "rights": ["playback"]}],
        }
    ]
    groups = client_for(lambda request: httpx.Response(200, json=body)).my_groups()
    assert groups[0].consents[0].id == "consent-1"


def test_consents_are_listed_for_one_group_created_and_revoked():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.url.query.decode()))
        item = {
            "id": "consent-1",
            "community_id": "my-family",
            "rights": ["playback"],
            "policy_version": "v1",
            "revoked": False,
        }
        return httpx.Response(200, json=[item] if request.method == "GET" else item)

    client = client_for(handler)
    assert client.consents("my-family")[0].id == "consent-1"
    assert client.create_consent("my-family", ["playback"]).community_id == "my-family"
    client.revoke_consent("consent-1")
    assert seen[0] == ("GET", "/admin/consents", "community_id=my-family")
    assert seen[2] == ("POST", "/admin/consents/consent-1/revoke", "")


def test_members_can_be_listed_added_and_removed():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200, json={"sub": "aunt-1"})
        item = {"sub": "aunt-1", "email": "aunt@example.org"}
        return httpx.Response(200, json=[item] if request.method == "GET" else item)

    client = client_for(handler)
    assert client.members("my-family")[0].email == "aunt@example.org"
    assert client.add_member("my-family", "aunt@example.org").sub == "aunt-1"
    client.remove_member("my-family", "aunt-1")
    assert seen == [
        ("GET", "/admin/groups/my-family/members"),
        ("POST", "/admin/groups/my-family/members"),
        ("DELETE", "/admin/groups/my-family/members/aunt-1"),
    ]


def test_open_consent_sends_the_confirmation_and_returns_the_reference():
    sent = {}

    def handler(request):
        sent["body"] = request.content
        return httpx.Response(201, json={"consent_id": "consent-1", "community_id": "everyone"})

    assert client_for(handler).give_open_consent(True, False) == "consent-1"
    assert b'"confirm":true' in sent["body"]
    assert b'"attribution":false' in sent["body"]
