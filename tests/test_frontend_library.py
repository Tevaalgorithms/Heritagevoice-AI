import httpx

from frontend.api_client import ApiClient, LibraryItem, LibrarySpec
from frontend.theme import passage_html
from frontend.views.library import _heading, _kind_options, _language_options

ITEM = {
    "evidence_id": "r1:transcript:v1:c0",
    "recording_id": "r1",
    "heritage_kind": "remedy",
    "language": "ta",
    "view": "original",
    "passage": "வணக்கம்",
    "start_s": 0.0,
    "end_s": 4.0,
    "notices": ["Not medically validated. Shared from the traditional notes of elders."],
    "community": None,
}


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_only_the_filters_that_are_set_are_sent():
    seen = {}

    def handler(request):
        seen["path"], seen["query"] = request.url.path, dict(request.url.params)
        return httpx.Response(200, json={"items": [ITEM]})

    result = client_for(handler).library(LibrarySpec(q="water", language="ta", view="translation"))
    assert seen["path"] == "/v1/library"
    assert seen["query"] == {"q": "water", "language": "ta", "view": "translation", "limit": "20"}
    assert result.items[0].notices == ITEM["notices"]


def test_browsing_sends_no_search_text():
    seen = {}

    def handler(request):
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"items": []})

    client_for(handler).library(LibrarySpec())
    assert "q" not in seen["query"]
    assert "language" not in seen["query"]


def test_an_admin_changes_visibility_through_the_endpoint():
    seen = {}

    def handler(request):
        seen["call"] = (request.method, request.url.path, request.read())
        return httpx.Response(200, json={"recording_id": "r1", "visibility": "public"})

    result = client_for(handler).set_visibility("r1", "public")
    assert seen["call"][:2] == ("PUT", "/v1/recordings/r1/visibility")
    assert b'"public"' in seen["call"][2]
    assert result.visibility == "public"


def test_passage_text_can_never_inject_markup_or_links():
    html = passage_html("<script>alert(1)</script> ![x](http://evil.example/p.png) <b>hi</b>")
    assert "<script" not in html
    assert "<b>" not in html
    assert "&lt;script&gt;" in html
    assert html.startswith("<div class='hv-passage'>")


def test_the_heading_names_the_kind_and_the_language_and_credits_only_when_given():
    anonymous = LibraryItem(**ITEM)
    assert "Traditional remedy" in _heading(anonymous)
    assert "தமிழ்" in _heading(anonymous)
    assert "community" not in _heading(anonymous)
    credited = LibraryItem(**{**ITEM, "community": "c2"})
    assert "from the c2 community" in _heading(credited)


def test_the_filter_choices_cover_every_language_and_kind_and_start_with_any():
    assert list(_language_options().values())[0] == ""
    assert {"ta", "hi", "te", "fr"} <= set(_language_options().values())
    assert set(_kind_options().values()) == {"", "story", "song", "lesson", "practice", "remedy"}
