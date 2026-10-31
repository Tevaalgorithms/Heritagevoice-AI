import httpx

from frontend.api_client import ApiClient
from frontend.theme import answer_html
from frontend.views.ask import STATUS_NOTES, answer_for

BODY = {
    "status": "answered",
    "answer": "Water was shared [1].",
    "citations": [
        {
            "evidence_id": "e1",
            "recording_id": "r1",
            "title": "Recording r1",
            "passage": "We shared the water.",
            "start_s": 1.0,
            "end_s": 5.0,
            "notices": ["Not medically validated. Shared from the traditional notes of elders."],
        }
    ],
    "warnings": ["graph_unavailable"],
    "request_id": "abc",
}


def client_for(handler):
    return ApiClient("http://api.test", "tok", transport=httpx.MockTransport(handler))


def test_a_question_goes_to_the_v1_endpoint_and_the_sources_are_parsed():
    seen = {}

    def handler(request):
        seen["call"] = (request.method, request.url.path, request.read())
        return httpx.Response(200, json=BODY)

    result = client_for(handler).query("How was water shared?")
    assert seen["call"][:2] == ("POST", "/v1/query")
    assert b"How was water shared?" in seen["call"][2]
    assert result.citations[0].notices
    assert (result.citations[0].start_s, result.citations[0].end_s) == (1.0, 5.0)
    assert result.warnings == ["graph_unavailable"]


def test_an_answer_can_never_inject_markup_or_links():
    html = answer_html("Hi <script>alert(1)</script> [link](http://evil.example) <img src=x>\nNext")
    assert "<script" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "<br>Next" in html


def test_partial_and_insufficient_answers_carry_a_plain_note():
    assert set(STATUS_NOTES) == {"partial", "insufficient_evidence"}
    assert all(STATUS_NOTES.values())


def test_a_failed_question_becomes_a_friendly_message_not_an_exception(monkeypatch):
    def handler(request):
        return httpx.Response(504, json={"detail": {"code": "deadline"}})

    class Quiet:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("frontend.views.ask.st.spinner", lambda text: Quiet())
    turn = answer_for(client_for(handler), "q")
    assert turn["role"] == "assistant"
    assert "too long" in str(turn["content"])
    assert turn["result"] is None


def test_the_chosen_answer_language_is_sent_and_the_default_sends_none():
    sent = []

    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json={"status": "answered", "answer": "x", "request_id": "r"})

    client_for(handler).query("Q?", "ta")
    client_for(handler).query("Q?")
    assert b'"response_language":"ta"' in sent[0]
    assert b'"response_language":null' in sent[1]


def test_every_supported_language_can_be_chosen_for_the_answer():
    from app.languages import LANGUAGES  # noqa: PLC0415
    from frontend.views.ask import ANSWER_LANGUAGES, SAME  # noqa: PLC0415

    assert ANSWER_LANGUAGES[SAME] is None
    assert set(ANSWER_LANGUAGES.values()) - {None} == {lang.code for lang in LANGUAGES}


def _exchange(question, answer, ok=True):
    return [
        {"role": "user", "content": question, "result": None},
        {"role": "assistant", "content": answer, "result": object() if ok else None},
    ]


def test_the_last_three_finished_exchanges_are_remembered_and_shortened():
    from frontend.views.ask import remembered  # noqa: PLC0415

    messages = []
    for n in range(5):
        messages += _exchange(f"q{n}" + "x" * 600, f"a{n}" + "y" * 700)
    turns = remembered(messages)
    assert [t["question"][:2] for t in turns] == ["q2", "q3", "q4"]
    assert all(len(t["question"]) == 500 and len(t["answer"]) == 600 for t in turns)


def test_a_failed_answer_is_not_remembered():
    from frontend.views.ask import remembered  # noqa: PLC0415

    messages = _exchange("q1", "a1") + _exchange("q2", "The API is unavailable.", ok=False)
    assert remembered(messages) == [{"question": "q1", "answer": "a1"}]


def test_history_is_sent_with_the_question():
    sent = []

    def handler(request):
        sent.append(request.content)
        return httpx.Response(200, json={"status": "answered", "answer": "x", "request_id": "r"})

    client_for(handler).query("And then?", None, [{"question": "q", "answer": "a"}])
    client_for(handler).query("First")
    assert b'"history":[{"question":"q","answer":"a"}]' in sent[0]
    assert b'"history":[]' in sent[1]
