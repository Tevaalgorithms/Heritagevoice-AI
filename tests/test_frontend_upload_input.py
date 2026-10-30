import io

from frontend.account import current_role
from frontend.api_client import ApiRequestError
from frontend.upload_input import idempotency_key, pick_audio


class Audio(io.BytesIO):
    """Stands in for Streamlit's uploaded-file object."""


def test_nothing_chosen_means_no_audio():
    assert pick_audio(None, None) is None


def test_a_file_alone_is_used():
    assert pick_audio(None, Audio(b"file")) == b"file"


def test_a_recording_alone_is_used():
    assert pick_audio(Audio(b"mic"), None) == b"mic"


def test_a_fresh_recording_wins_over_a_file_left_in_the_other_tab():
    assert pick_audio(Audio(b"mic"), Audio(b"file")) == b"mic"


def test_an_empty_recording_is_still_a_recording_not_a_missing_one():
    assert pick_audio(Audio(b""), Audio(b"file")) == b""


def test_the_same_audio_gets_the_same_key_so_a_double_click_is_one_upload():
    assert idempotency_key(b"abc") == idempotency_key(b"abc")


def test_a_different_recording_in_the_same_session_gets_a_different_key():
    assert idempotency_key(b"first") != idempotency_key(b"second")


def test_the_key_fits_what_the_api_accepts():
    import re  # noqa: PLC0415

    assert re.fullmatch(r"[A-Za-z0-9_-]{8,64}", idempotency_key(b"x"))


def test_the_role_is_read_from_the_server_and_a_failure_is_not_fatal():
    class Me:
        role = "reviewer"

    class Good:
        def me(self):
            return Me()

    class Down:
        def me(self):
            raise ApiRequestError(500)

    assert current_role(Good()) == "reviewer"
    assert current_role(Down()) is None
