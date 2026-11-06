"""Credit and source in the words readers see: plain text only, and only what was given."""

import httpx
import pytest

from frontend.api_client import ApiClient
from frontend.api_models import CitationView, LibraryItem, UploadSpec
from frontend.credit import (
    NOT_GIVEN,
    SOURCE_LABELS,
    UPLOAD_CHOICES,
    long_date,
    origin_line,
    plain,
    source_phrase,
)


def test_markdown_in_a_name_or_note_is_escaped_so_it_cannot_format_or_link():
    shown = plain("**bold** [click](https://evil.example) <b>")
    assert "\\*\\*bold\\*\\*" in shown
    assert "\\[click\\]\\(https://evil" in shown
    assert "\\<b\\>" in shown


@pytest.mark.parametrize(
    ("iso", "text"),
    [("2026-11-05", "5 Nov 2026"), ("2026-01-31", "31 Jan 2026"), ("not a date", "not a date")],
)
def test_dates_read_naturally(iso, text):
    assert long_date(iso) == text


def test_the_source_reads_as_a_kind_with_optional_details():
    assert source_phrase("family", "Jaffna") == "Told by a grandparent or family elder: Jaffna"
    assert source_phrase("book", None) == "From a book or publication"
    assert source_phrase(None, "a note") == "a note"
    assert source_phrase(None, None) == ""


def test_the_origin_line_names_who_where_and_when_in_that_order():
    line = origin_line("2026-11-05", "Amma Selvi", "family", "Jaffna")
    assert line.replace("\\", "") == (
        "Shared by Amma Selvi · Told by a grandparent or family elder: Jaffna · Added 5 Nov 2026"
    )


def test_without_a_credit_only_the_date_is_shown():
    assert origin_line("2026-11-05", None, None, None) == "Added 5 Nov 2026"


def test_with_nothing_known_nothing_is_shown():
    assert origin_line("", None, None, None) == ""


def test_every_source_kind_the_server_knows_has_a_label_and_an_upload_choice():
    assert set(SOURCE_LABELS) == {"own", "family", "elder", "book", "website", "other"}
    assert UPLOAD_CHOICES[NOT_GIVEN] == ""
    assert set(UPLOAD_CHOICES.values()) == {"", *SOURCE_LABELS}


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def sent_form(spec):
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode(errors="replace")
        return httpx.Response(201, json={"recording_id": "r1", "job_id": "j1"})

    client_for(handler).upload_recording(spec, "key-00000001")
    return seen["body"]


def spec(**extra):
    return UploadSpec(data=b"audio", language="ta", community_id="c1", consent_id="k1", **extra)


def test_the_credit_fields_are_sent_when_filled_in():
    body = sent_form(spec(credit_name="Amma Selvi", source_kind="family", source_note="Jaffna"))
    for field, value in (
        ("credit_name", "Amma Selvi"),
        ("source_kind", "family"),
        ("source_note", "Jaffna"),
    ):
        assert f'name="{field}"' in body
        assert value in body


def test_empty_credit_fields_are_not_sent_at_all():
    body = sent_form(spec())
    for field in ("credit_name", "source_kind", "source_note"):
        assert f'name="{field}"' not in body


def test_a_library_item_and_a_citation_read_the_credit_the_server_sent():
    credit = {"name": "Amma Selvi", "source_kind": "book", "source_note": None}
    item = LibraryItem.model_validate(
        {
            "evidence_id": "e1",
            "recording_id": "r1",
            "heritage_kind": "story",
            "language": "ta",
            "view": "original",
            "passage": "p",
            "start_s": 0,
            "end_s": 1,
            "added": "2026-11-05",
            "credit": credit,
        }
    )
    assert (item.added, item.credit.name, item.credit.source_kind) == (
        "2026-11-05",
        "Amma Selvi",
        "book",
    )
    cited = CitationView.model_validate(
        {
            "evidence_id": "e1",
            "recording_id": "r1",
            "title": "t",
            "passage": "p",
            "start_s": 0,
            "end_s": 1,
        }
    )
    assert cited.credit is None
    assert cited.added == ""


# --- connections ---------------------------------------------------------------------------


def test_the_connections_call_uses_the_signed_in_or_the_public_endpoint():
    seen = []

    def handler(request):
        seen.append(
            (request.url.path, request.url.query.decode(), request.headers.get("authorization"))
        )
        return httpx.Response(200, json={"items": []})

    ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler)).connections(
        "humility"
    )
    ApiClient("http://api.test", None, transport=httpx.MockTransport(handler)).connections("")
    assert seen[0] == ("/v1/connections", "q=humility", "Bearer tok")
    assert seen[1] == ("/v1/public/connections", "", None)


def test_a_client_knows_whether_someone_is_signed_in():
    assert ApiClient("http://api.test", "tok").signed_in is True
    assert ApiClient("http://api.test", None).signed_in is False


def test_a_connection_headline_names_both_sides_and_escapes_them():
    from frontend.relations import headline_html  # noqa: PLC0415

    line = headline_html("<script>x</script>", "TEACHES", "பணிவு")
    assert "<script>" not in line
    assert "&lt;script&gt;" in line
    assert line.endswith("teaches <b>பணிவு</b>")


def test_a_connection_parses_with_its_passage_and_origin():
    from frontend.api_models import ConnectionResult  # noqa: PLC0415

    result = ConnectionResult.model_validate(
        {
            "items": [
                {
                    "assertion_id": "a1",
                    "subject": "proverb",
                    "relation": "TEACHES",
                    "object": "humility",
                    "recording_id": "r1",
                    "evidence_id": "e1",
                    "passage": "p",
                    "start_s": 0.9,
                    "end_s": 2.7,
                    "added": "2026-11-05",
                }
            ]
        }
    )
    assert (result.items[0].relation, result.items[0].credit, result.items[0].added) == (
        "TEACHES",
        None,
        "2026-11-05",
    )


def test_a_citation_carries_how_it_was_connected():
    cited = CitationView.model_validate(
        {
            "evidence_id": "e1",
            "recording_id": "r1",
            "title": "t",
            "passage": "p",
            "start_s": 0,
            "end_s": 1,
            "connections": ["the proverb teaches humility"],
        }
    )
    assert cited.connections == ["the proverb teaches humility"]
