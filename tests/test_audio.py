import io
import wave
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from app.adapters.audio_store import LocalAudioStore, S3AudioStore
from app.audio import (
    BAD_LANGUAGE,
    EMPTY,
    TOO_LARGE,
    TOO_LONG,
    UNREADABLE,
    UNSUPPORTED_TYPE,
    AudioRules,
    UploadError,
    check_language,
    sniff_type,
    validate_audio,
)
from app.fakes import FakeAudioStore
from app.ports import AudioStore

RULES = AudioRules(max_bytes=1_000_000, max_seconds=5.0, languages=frozenset({"ta", "en"}))


def wav_bytes(seconds=1.0, rate=8000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def test_a_valid_wav_is_accepted_with_its_measured_duration():
    info = validate_audio(wav_bytes(2.0), RULES)
    assert info.content_type == "audio/wav"
    assert info.duration_s == pytest.approx(2.0, abs=0.01)
    assert info.size_bytes == len(wav_bytes(2.0))


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"),
        (b"ID3\x04\x00\x00", "audio/mpeg"),
        (b"\xff\xfb\x90\x00", "audio/mpeg"),
        (b"fLaC\x00\x00", "audio/flac"),
        (b"OggS\x00\x02", "audio/ogg"),
        (b"\x00\x00\x00\x18ftypM4A ", "audio/mp4"),
        (b"MZ\x90\x00", None),
        (b"<html>", None),
        (b"", None),
    ],
)
def test_the_type_comes_from_the_bytes(head, expected):
    assert sniff_type(head) == expected


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", EMPTY),
        (b"not audio at all, just text pretending", UNSUPPORTED_TYPE),
        (b"MZ" + b"\x00" * 100, UNSUPPORTED_TYPE),
        (wav_bytes(1.0) + b"x" * 1_000_000, TOO_LARGE),
        (wav_bytes(6.0), TOO_LONG),
        (b"RIFF\x00\x00\x00\x00WAVEbroken", UNREADABLE),
    ],
    ids=["empty", "text", "executable", "too-large", "too-long", "corrupt"],
)
def test_bad_audio_is_rejected_with_a_safe_code(data, code):
    with pytest.raises(UploadError) as error:
        validate_audio(data, RULES)
    assert error.value.code == code


def test_language_must_be_allowed():
    check_language("ta", RULES)
    with pytest.raises(UploadError) as error:
        check_language("fr", RULES)
    assert (error.value.code, error.value.status_code) == (BAD_LANGUAGE, 422)


def test_a_renamed_file_is_still_judged_by_its_content():
    assert sniff_type(b"MZ\x90\x00 recording.mp3") is None


@pytest.fixture
def local_store(tmp_path):
    return LocalAudioStore(tmp_path)


def test_local_store_round_trips_and_deletes(local_store, tmp_path):
    local_store.put("recordings/c1/r1/original", b"audio", "audio/wav")
    assert local_store.get("recordings/c1/r1/original") == b"audio"
    local_store.delete("recordings/c1/r1/original")
    assert not Path(tmp_path / "recordings/c1/r1/original").exists()
    local_store.delete("recordings/c1/r1/original")


@pytest.mark.parametrize(
    "key", ["../escape", "/abs/path", "a//b", "a/../b", "has space", "x" * 201, "", "a/b.wav"]
)
def test_unsafe_storage_keys_are_rejected(local_store, key):
    with pytest.raises(ValueError, match="Invalid storage key"):
        local_store.put(key, b"x", "audio/wav")


def test_stores_satisfy_the_port(local_store):
    assert isinstance(local_store, AudioStore)
    assert isinstance(FakeAudioStore(), AudioStore)
    assert isinstance(S3AudioStore("bucket", client=object()), AudioStore)


def s3_client():
    return boto3.client(
        "s3",
        region_name="eu-west-2",
        aws_access_key_id="test-only",
        aws_secret_access_key="test-only",  # noqa: S106
    )


def test_s3_objects_are_written_encrypted_with_kms():
    client = s3_client()
    store = S3AudioStore("audio-bucket", "kms-key-1", client)
    with Stubber(client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": "audio-bucket",
                "Key": "recordings/c1/r1/original",
                "Body": b"audio",
                "ContentType": "audio/wav",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": "kms-key-1",
            },
        )
        store.put("recordings/c1/r1/original", b"audio", "audio/wav")
        stubber.assert_no_pending_responses()


def test_s3_get_and_delete_use_the_checked_key():
    client = s3_client()
    store = S3AudioStore("audio-bucket", None, client)
    with Stubber(client) as stubber:
        stubber.add_response(
            "get_object",
            {"Body": io.BytesIO(b"audio")},
            {"Bucket": "audio-bucket", "Key": "recordings/c1/r1/original"},
        )
        stubber.add_response(
            "delete_object", {}, {"Bucket": "audio-bucket", "Key": "recordings/c1/r1/original"}
        )
        assert store.get("recordings/c1/r1/original") == b"audio"
        store.delete("recordings/c1/r1/original")
        with pytest.raises(ValueError, match="Invalid storage key"):
            store.get("../other")
