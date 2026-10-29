import io
import json

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.adapters.transcribe import (
    MAX_WORDS,
    AmazonTranscribe,
    Runtime,
    TranscribeConfig,
    segments_from_items,
)
from app.config import Settings
from app.db.engine import make_engine
from app.db.tables import Base
from app.errors import ProviderError
from app.ports import Transcriber
from app.worker_setup import build_handlers


def word(text, start, end, speaker=None):
    item = {
        "type": "pronunciation",
        "start_time": str(start),
        "end_time": str(end),
        "alternatives": [{"confidence": "0.99", "content": text}],
    }
    return {**item, "speaker_label": speaker} if speaker else item


def mark(text):
    return {"type": "punctuation", "alternatives": [{"confidence": "0.0", "content": text}]}


def test_sentences_become_timed_segments_with_stable_ids():
    items = [
        word("How", 0.0, 0.3),
        word("are", 0.3, 0.5),
        word("you", 0.5, 0.9),
        mark("?"),
        word("Fine", 1.0, 1.4),
        mark("."),
    ]
    first, second = segments_from_items(items)
    assert (first.segment_id, first.start_s, first.end_s, first.text) == (
        "s1",
        0.0,
        0.9,
        "How are you?",
    )
    assert (second.segment_id, second.start_s, second.end_s, second.text) == (
        "s2",
        1.0,
        1.4,
        "Fine.",
    )


def test_tamil_text_is_kept_as_is():
    (segment,) = segments_from_items([word("வணக்கம்", 0.0, 0.6), mark(".")])
    assert segment.text == "வணக்கம்."


def test_a_long_pause_starts_a_new_segment():
    items = [word("one", 0.0, 0.4), word("two", 3.0, 3.4)]
    assert [s.text for s in segments_from_items(items)] == ["one", "two"]


def test_long_runs_are_split_at_a_maximum_length():
    items = [word(f"w{i}", i * 0.1, i * 0.1 + 0.1) for i in range(MAX_WORDS + 5)]
    assert [len(s.text.split()) for s in segments_from_items(items)] == [MAX_WORDS, 5]


def test_a_change_of_speaker_starts_a_new_segment_and_is_recorded():
    items = [word("hi", 0.0, 0.2, "spk_0"), word("hello", 0.2, 0.5, "spk_1")]
    assert [s.speaker for s in segments_from_items(items)] == ["spk_0", "spk_1"]


def test_zero_length_words_still_give_valid_segments():
    (segment,) = segments_from_items([word("hm", 1.0, 1.0)])
    assert segment.end_s > segment.start_s


def test_no_items_means_no_segments():
    assert segments_from_items([]) == []


def clients():
    kwargs = {
        "region_name": "eu-west-2",
        "aws_access_key_id": "test-only",
        "aws_secret_access_key": "test-only",  # noqa: S106
    }
    return boto3.client("transcribe", **kwargs), boto3.client("s3", **kwargs)


OUTPUT = json.dumps({"results": {"items": [word("hello", 0.0, 0.4), mark(".")]}}).encode()
START_PARAMS = {
    "TranscriptionJobName": ANY,
    "LanguageCode": "ta-IN",
    "Media": {"MediaFileUri": "s3://audio-bucket/recordings/c1/r1/original"},
    "OutputBucketName": "audio-bucket",
    "OutputKey": ANY,
}


def job(status):
    return {"TranscriptionJob": {"TranscriptionJobStatus": status}}


@pytest.fixture
def harness():
    transcribe, s3 = clients()
    sleeps = []
    runtime = Runtime(transcribe, s3, sleeps.append, lambda: "hv-test-job")
    asr = AmazonTranscribe(
        TranscribeConfig("audio-bucket", poll_seconds=5, timeout_seconds=10), runtime
    )
    with Stubber(transcribe) as t_stub, Stubber(s3) as s_stub:
        yield asr, t_stub, s_stub, sleeps


def test_a_completed_job_is_parsed_then_the_provider_copies_are_deleted(harness):
    asr, t_stub, s_stub, sleeps = harness
    t_stub.add_response("start_transcription_job", {}, START_PARAMS)
    t_stub.add_response(
        "get_transcription_job", job("IN_PROGRESS"), {"TranscriptionJobName": "hv-test-job"}
    )
    t_stub.add_response(
        "get_transcription_job", job("COMPLETED"), {"TranscriptionJobName": "hv-test-job"}
    )
    t_stub.add_response("delete_transcription_job", {}, {"TranscriptionJobName": "hv-test-job"})
    s_stub.add_response(
        "get_object",
        {"Body": io.BytesIO(OUTPUT)},
        {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"},
    )
    s_stub.add_response(
        "delete_object", {}, {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"}
    )
    (segment,) = asr.transcribe("recordings/c1/r1/original", "ta")
    assert (segment.segment_id, segment.text) == ("s1", "hello.")
    assert sleeps == [5]
    t_stub.assert_no_pending_responses()
    s_stub.assert_no_pending_responses()


def test_a_failed_job_raises_a_safe_error_and_still_cleans_up(harness):
    asr, t_stub, s_stub, _ = harness
    t_stub.add_response("start_transcription_job", {}, START_PARAMS)
    t_stub.add_response(
        "get_transcription_job", job("FAILED"), {"TranscriptionJobName": "hv-test-job"}
    )
    t_stub.add_response("delete_transcription_job", {}, {"TranscriptionJobName": "hv-test-job"})
    s_stub.add_response(
        "delete_object", {}, {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"}
    )
    with pytest.raises(ProviderError) as error:
        asr.transcribe("recordings/c1/r1/original", "ta")
    assert error.value.code == "asr"
    t_stub.assert_no_pending_responses()
    s_stub.assert_no_pending_responses()


def test_a_job_that_never_finishes_times_out(harness):
    asr, t_stub, s_stub, sleeps = harness
    t_stub.add_response("start_transcription_job", {}, START_PARAMS)
    for _ in range(3):
        t_stub.add_response(
            "get_transcription_job", job("IN_PROGRESS"), {"TranscriptionJobName": "hv-test-job"}
        )
    t_stub.add_response("delete_transcription_job", {}, {"TranscriptionJobName": "hv-test-job"})
    s_stub.add_response(
        "delete_object", {}, {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"}
    )
    with pytest.raises(ProviderError, match="timed out"):
        asr.transcribe("recordings/c1/r1/original", "ta")
    assert sleeps == [5, 5, 5]


def test_a_service_error_when_starting_becomes_a_provider_error(harness):
    asr, t_stub, s_stub, _ = harness
    t_stub.add_client_error("start_transcription_job", "ThrottlingException")
    t_stub.add_response("delete_transcription_job", {}, {"TranscriptionJobName": "hv-test-job"})
    s_stub.add_response(
        "delete_object", {}, {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"}
    )
    with pytest.raises(ProviderError) as error:
        asr.transcribe("recordings/c1/r1/original", "ta")
    assert error.value.code == "asr"


def test_a_cleanup_failure_does_not_lose_the_transcript(harness):
    asr, t_stub, s_stub, _ = harness
    t_stub.add_response("start_transcription_job", {}, START_PARAMS)
    t_stub.add_response(
        "get_transcription_job", job("COMPLETED"), {"TranscriptionJobName": "hv-test-job"}
    )
    t_stub.add_client_error("delete_transcription_job", "BadRequestException")
    s_stub.add_response(
        "get_object",
        {"Body": io.BytesIO(OUTPUT)},
        {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"},
    )
    s_stub.add_client_error("delete_object", "AccessDenied")
    assert len(asr.transcribe("recordings/c1/r1/original", "ta")) == 1


def test_an_unsupported_language_fails_before_any_service_call(harness):
    asr, t_stub, s_stub, _ = harness
    with pytest.raises(ProviderError) as error:
        asr.transcribe("recordings/c1/r1/original", "fr")
    assert error.value.code == "asr"
    t_stub.assert_no_pending_responses()


def test_the_output_is_encrypted_with_the_configured_kms_key():
    transcribe, s3 = clients()
    runtime = Runtime(transcribe, s3, lambda seconds: None, lambda: "hv-test-job")
    asr = AmazonTranscribe(TranscribeConfig("audio-bucket", kms_key_id="kms-1"), runtime)
    with Stubber(transcribe) as t_stub, Stubber(s3) as s_stub:
        t_stub.add_response(
            "start_transcription_job", {}, {**START_PARAMS, "OutputEncryptionKMSKeyId": "kms-1"}
        )
        t_stub.add_response(
            "get_transcription_job", job("COMPLETED"), {"TranscriptionJobName": "hv-test-job"}
        )
        t_stub.add_response("delete_transcription_job", {}, {"TranscriptionJobName": "hv-test-job"})
        s_stub.add_response(
            "get_object",
            {"Body": io.BytesIO(OUTPUT)},
            {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"},
        )
        s_stub.add_response(
            "delete_object", {}, {"Bucket": "audio-bucket", "Key": "transcripts/hv-test-job.json"}
        )
        asr.transcribe("recordings/c1/r1/original", "ta")
        t_stub.assert_no_pending_responses()


def test_the_adapter_satisfies_the_port():
    transcribe, s3 = clients()
    assert isinstance(AmazonTranscribe(TranscribeConfig("b"), Runtime(transcribe, s3)), Transcriber)


@pytest.fixture
def engine():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_no_speech_service_means_no_ingest_handler(engine):
    assert build_handlers(Settings(_env_file=None), engine) == {}


def test_a_bucket_enables_the_ingest_handler(engine):
    handlers = build_handlers(Settings(_env_file=None, audio_bucket="audio-bucket"), engine)
    assert set(handlers) == {"ingest_recording"}


def test_the_fake_speech_service_is_refused_outside_the_local_environment(engine):
    local = Settings(_env_file=None, asr_provider="fake", environment="local")
    prod = Settings(_env_file=None, asr_provider="fake", environment="production")
    assert set(build_handlers(local, engine)) == {"ingest_recording"}
    assert build_handlers(prod, engine) == {}
