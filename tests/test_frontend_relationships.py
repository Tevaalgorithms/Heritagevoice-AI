import httpx

from app.models.records import Relation
from frontend.api_client import ApiClient, AssertionEditSpec
from frontend.relations import RELATIONS, phrase
from frontend.views.relationships import _headline


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


ITEM = {
    "id": "a1",
    "recording_id": "r1",
    "subject": "Amma",
    "relation": "MENTIONS",
    "object": "the well",
    "asserted_by": "Amma",
    "review_state": "pending",
    "confidence": 0.6,
    "start_s": 0.0,
    "end_s": 4.0,
    "passage": "x",
}


def test_every_relation_the_server_accepts_has_a_plain_phrase():
    assert set(RELATIONS) == {r.value for r in Relation} - {"SUPPORTED_BY"}
    assert phrase("MENTIONS") == "mentions"
    assert phrase("SOMETHING_NEW") == "SOMETHING_NEW"


def test_names_in_a_proposal_are_escaped_before_display():
    item = client_for(lambda r: httpx.Response(200, json=[ITEM])).assertions("pending")[0]
    hostile = item.model_copy(update={"subject": "<script>alert(1)</script>"})
    assert "<script>" not in _headline(hostile)


def test_proposals_are_listed_by_state_and_decisions_send_only_the_changes():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.url.query.decode(), request.content))
        return httpx.Response(200, json=[ITEM] if request.method == "GET" else {})

    client = client_for(handler)
    assert client.assertions("pending")[0].subject == "Amma"
    client.decide_assertion("a1", True, AssertionEditSpec(subject="Amma Lakshmi"))
    assert seen[0][:3] == ("GET", "/v1/graph/assertions", "state=pending")
    assert seen[1][1] == "/v1/graph/assertions/a1/decision"
    assert b'"subject":"Amma Lakshmi"' in seen[1][3]
    assert b"relation" not in seen[1][3]
