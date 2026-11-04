"""Correct a relationship by speaking: what is heard, how it is read, and that audio never stays."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.correction_interpreter import CorrectionInterpreter, Interpretation
from app.api.auth import current_principal, get_session_factory
from app.api.graph_voice import get_voice_deps, get_voice_limiter
from app.api.main import app
from app.audio import AudioRules, UploadError
from app.db.repositories import GraphAssertionRepository
from app.db.session import session_scope
from app.db.tables import AuditLogRow, Base
from app.errors import ProviderError
from app.fakes import FakeTranscriber, FakeTranslator
from app.models.records import GraphAssertion, Relation, ReviewState
from app.models.transcript import Segment
from app.ratelimit import SlidingWindowLimiter
from app.security.roles import Role
from app.voice_correction import Spoken, VoiceDeps, understand_correction
from tests.helpers import person, wav_bytes
from tests.index_helpers import published

ADMIN = person(Role.ADMIN, user_id="admin-1", communities=())
RULES = AudioRules(max_bytes=1_000_000, max_seconds=300.0, languages=frozenset({"ta", "en"}))
HEARD = [Segment(segment_id="s1", start_s=0, end_s=2, text="இது பணிவு பற்றியது")]
CORRECTED = Interpretation(
    understood=True, subject="யானை", relation=Relation.TEACHES, object="பணிவு"
)


class Store:
    def __init__(self):
        self.puts, self.deletes = [], []

    def put(self, key, data, content_type):
        self.puts.append(key)

    def get(self, key):
        raise AssertionError("never read back")

    def delete(self, key):
        self.deletes.append(key)


class Runner:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def invoke(self, inputs):
        self.calls.append(inputs)
        return self.reply


class Failing:
    def transcribe(self, audio_key, language):
        raise ProviderError("down", code="asr")


def deps(transcriber=None, reply=CORRECTED, store=None, rules=RULES):
    runner = Runner(reply)
    built = VoiceDeps(
        store or Store(),
        transcriber or FakeTranscriber(HEARD),
        FakeTranslator(),
        CorrectionInterpreter(runner),
        rules,
    )
    return built, runner


def assertion(aid="a1", state=ReviewState.PENDING, **fields):
    values = {
        "id": aid, "recording_id": "r1", "subject": "யானைக்கும் அடி சறுக்கும்",
        "relation": Relation.DESCRIBES, "object": "யானை", "asserted_by": "unknown",
        "review_state": state, "supporting_segment_id": "s1", "transcript_version": 1,
        "confidence": 0.4, "policy_ref": "v1",
    }  # fmt: skip
    return GraphAssertion(**{**values, **fields})


def spoken(language="ta", seconds=2.0):
    return Spoken(wav_bytes(seconds), language)


def test_a_spoken_correction_is_heard_translated_and_read():
    built, runner = deps()
    fix = understand_correction(assertion(), "the saying", spoken(), built)
    assert fix.heard == "இது பணிவு பற்றியது"
    assert fix.english == "[en] இது பணிவு பற்றியது"
    assert fix.suggestion == CORRECTED
    assert runner.calls[0]["english"] == fix.english
    assert "TEACHES" not in runner.calls[0]["proposed"]  # the proposal as it stood


def test_the_audio_is_deleted_after_it_is_transcribed():
    store = Store()
    built, _ = deps(store=store)
    understand_correction(assertion(), "p", spoken(), built)
    assert len(store.puts) == 1
    assert store.deletes == store.puts
    assert store.puts[0].startswith("corrections/a1/")


def test_the_audio_is_deleted_even_when_transcription_fails():
    store = Store()
    built, _ = deps(transcriber=Failing(), store=store)
    with pytest.raises(ProviderError):
        understand_correction(assertion(), "p", spoken(), built)
    assert store.puts
    assert store.deletes == store.puts


def test_english_speech_is_not_translated():
    built, runner = deps()
    fix = understand_correction(assertion(), "p", spoken("en"), built)
    assert fix.english == fix.heard


def test_silence_stops_before_any_model_is_asked():
    built, runner = deps(transcriber=FakeTranscriber([]))
    fix = understand_correction(assertion(), "p", spoken(), built)
    assert (fix.heard, fix.english, fix.suggestion) == ("", "", None)
    assert runner.calls == []


def test_an_unclear_correction_gives_no_suggestion():
    built, _ = deps(reply=Interpretation(understood=False))
    assert understand_correction(assertion(), "p", spoken(), built).suggestion is None


@pytest.mark.parametrize(
    "reply",
    [
        Interpretation(understood=True, subject="யானை", relation=Relation.TEACHES, object="யானை"),
        Interpretation(understood=True, subject="", relation=Relation.TEACHES, object="பணிவு"),
        Interpretation(understood=True, subject="a", relation=Relation.SUPPORTED_BY, object="b"),
        Interpretation(understood=True, subject="a" * 201, relation=Relation.TEACHES, object="b"),
    ],
)
def test_an_answer_that_does_not_make_sense_is_dropped(reply):
    built, _ = deps(reply=reply)
    assert understand_correction(assertion(), "p", spoken(), built).suggestion is None


def test_names_are_tidied():
    messy = Interpretation(
        understood=True, subject="  a   b ", relation=Relation.TEACHES, object="c"
    )
    built, _ = deps(reply=messy)
    found = understand_correction(assertion(), "p", spoken(), built).suggestion
    assert found is not None
    assert found.subject == "a b"


def test_a_wrong_model_answer_is_a_provider_error():
    built, _ = deps(reply="not an interpretation")
    with pytest.raises(ProviderError):
        understand_correction(assertion(), "p", spoken(), built)


def test_a_long_recording_is_refused_before_anything_is_stored():
    store = Store()
    built, _ = deps(store=store)
    with pytest.raises(UploadError) as error:
        understand_correction(assertion(), "p", spoken(seconds=90), built)
    assert error.value.code == "too_long"
    assert store.puts == []


def test_an_unsupported_language_is_refused():
    built, _ = deps()
    with pytest.raises(UploadError) as error:
        understand_correction(assertion(), "p", spoken("xx"), built)
    assert error.value.code == "bad_language"


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'voice.db'}")
    Base.metadata.create_all(engine)
    with session_scope(engine) as session:
        published(session)
        GraphAssertionRepository(session).add_many(
            [assertion("a1"), assertion("done", ReviewState.APPROVED)]
        )
    return engine


@pytest.fixture
def served(engine):
    built, runner = deps()
    app.dependency_overrides[get_session_factory] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[current_principal] = lambda: ADMIN
    app.dependency_overrides[get_voice_deps] = lambda: built
    app.dependency_overrides[get_voice_limiter] = lambda: SlidingWindowLimiter(100, 60.0)
    yield TestClient(app), built
    app.dependency_overrides.clear()


def send(client, aid="a1", language="ta", audio=None):
    files = {"file": ("correction", audio or wav_bytes(2.0), "application/octet-stream")}
    return client.post(
        f"/v1/graph/assertions/{aid}/voice", data={"language": language}, files=files
    )


def test_the_endpoint_returns_what_was_heard_and_a_suggestion(served):
    client, _ = served
    body = send(client).json()
    assert body["heard"] == "இது பணிவு பற்றியது"
    assert (body["understood"], body["relation"]) == (True, "TEACHES")
    assert (body["subject"], body["object"]) == ("யானை", "பணிவு")


def test_nothing_is_saved_and_the_audit_log_holds_no_words(served, engine):
    client, _ = served
    send(client)
    with Session(engine) as session:
        proposal = GraphAssertionRepository(session).get("a1")
        audit = session.query(AuditLogRow).one()
    assert (proposal.subject, proposal.relation, proposal.review_state) == (
        "யானைக்கும் அடி சறுக்கும்", Relation.DESCRIBES, ReviewState.PENDING,
    )  # fmt: skip
    assert audit.action == "graph:voice"
    assert audit.target == "graph:a1"
    assert "பணிவு" not in (audit.detail or "")


@pytest.mark.parametrize("role", [Role.MEMBER, Role.REVIEWER])
def test_only_admins_may_correct_by_voice(served, role):
    client, _ = served
    app.dependency_overrides[current_principal] = lambda: person(role)
    assert send(client).status_code == 403


def test_an_unknown_proposal_is_not_found(served):
    assert send(served[0], "nope").status_code == 404


def test_a_decided_proposal_cannot_be_corrected_by_voice(served):
    response = send(served[0], "done")
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "not_reviewable")


def test_a_recording_that_is_too_long_is_refused_with_its_code(served):
    response = send(served[0], audio=wav_bytes(90.0))
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "too_long")


def test_a_speech_service_failure_is_a_safe_error(served):
    client, built = served
    broken = VoiceDeps(built.store, Failing(), built.translator, built.interpreter, built.rules)
    app.dependency_overrides[get_voice_deps] = lambda: broken
    response = send(client)
    assert (response.status_code, response.json()["detail"]["code"]) == (502, "voice_failed")


def test_too_many_corrections_in_a_minute_are_refused(served):
    client, _ = served
    tight = SlidingWindowLimiter(1, 60.0)
    app.dependency_overrides[get_voice_limiter] = lambda: tight
    assert send(client).status_code == 200
    assert send(client).status_code == 429
