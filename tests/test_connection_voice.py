"""Search by voice: the words come back, the audio never stays, and the costs are limited."""

import pytest
from fastapi.testclient import TestClient

from app.api import connection_voice as voice
from app.api.auth import current_principal
from app.api.connection_voice import get_search_voice_deps
from app.api.main import app
from app.audio import AudioRules, UploadError
from app.errors import ProviderError
from app.fakes import FakeTranscriber
from app.models.transcript import Segment
from app.ratelimit import SlidingWindowLimiter
from app.voice_correction import Spoken
from app.voice_search import SearchVoiceDeps, hear
from tests.helpers import person, wav_bytes

RULES = AudioRules(max_bytes=10_000_000, max_seconds=300.0, languages=frozenset({"ta", "en"}))
HEARD = [Segment(segment_id="s1", start_s=0, end_s=2, text="பணிவு")]


class Store:
    def __init__(self):
        self.puts, self.deletes = [], []

    def put(self, key, data, content_type):
        self.puts.append(key)

    def get(self, key):
        raise AssertionError("never read back")

    def delete(self, key):
        self.deletes.append(key)


class Failing:
    def transcribe(self, audio_key, language):
        raise ProviderError("down", code="asr")


def deps(transcriber=None, store=None):
    return SearchVoiceDeps(store or Store(), transcriber or FakeTranscriber(HEARD), RULES)


def test_the_spoken_words_come_back_as_text():
    assert hear(Spoken(wav_bytes(2.0), "ta"), deps()) == "பணிவு"


def test_the_audio_is_deleted_even_when_transcription_fails():
    store = Store()
    with pytest.raises(ProviderError):
        hear(Spoken(wav_bytes(2.0), "ta"), deps(Failing(), store))
    assert store.puts
    assert store.deletes == store.puts


def test_a_long_clip_is_refused_before_anything_is_stored():
    store = Store()
    with pytest.raises(UploadError):
        hear(Spoken(wav_bytes(40.0), "ta"), deps(store=store))  # over the 15 seconds
    assert store.puts == []


def test_a_language_that_is_not_allowed_is_refused():
    with pytest.raises(UploadError):
        hear(Spoken(wav_bytes(2.0), "xx"), deps())


def test_silence_gives_no_words():
    assert hear(Spoken(wav_bytes(2.0), "ta"), deps(FakeTranscriber([]))) == ""


@pytest.fixture
def client():
    voice._READERS = SlidingWindowLimiter(2, 60.0)
    voice._VISITORS = SlidingWindowLimiter(2, 60.0)
    voice._ALL_VISITORS = SlidingWindowLimiter(3, 60.0)
    app.dependency_overrides[get_search_voice_deps] = deps
    app.dependency_overrides[current_principal] = lambda: person(communities=("c1",))
    yield TestClient(app)
    app.dependency_overrides.clear()


def speak(client, path, language="ta", seconds=2.0):
    return client.post(
        path, data={"language": language}, files={"file": ("a.wav", wav_bytes(seconds))}
    )


READER, VISITOR = "/v1/connections/voice", "/v1/public/connections/voice"


@pytest.mark.parametrize("path", [READER, VISITOR])
def test_both_a_reader_and_a_visitor_can_search_by_voice(client, path):
    response = speak(client, path)
    assert response.json() == {"heard": "பணிவு"}


def test_a_visitor_needs_no_sign_in_and_nothing_is_kept_by_browsers(client):
    app.dependency_overrides.pop(current_principal)
    response = speak(client, VISITOR)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", [READER, VISITOR])
def test_a_person_who_asks_too_often_is_slowed_down(client, path):
    assert speak(client, path).status_code == 200
    assert speak(client, path).status_code == 200
    third = speak(client, path)
    assert third.status_code == 429
    assert "retry-after" in third.headers


def test_visitors_together_cannot_run_up_the_transcription_bill(client):
    voice._VISITORS = SlidingWindowLimiter(100, 60.0)  # each visitor is fine, together too many
    assert [speak(client, VISITOR).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_a_clip_that_is_too_long_or_in_the_wrong_language_is_a_clear_error(client):
    assert speak(client, VISITOR, seconds=40.0).status_code in (400, 413, 422)
    assert speak(client, VISITOR, language="xx").status_code in (400, 422)


def test_it_is_unavailable_when_speech_to_text_is_not_set_up(client):
    app.dependency_overrides.pop(get_search_voice_deps)
    response = speak(client, VISITOR)
    assert response.status_code in (500, 503)
