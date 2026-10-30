import pytest

from app.adapters.transcribe import LANGUAGE_CODES
from app.config import Settings
from app.languages import BY_CODE, DEFAULT_ALLOWED, LANGUAGES
from app.retrieval.tokenize import tokens


def test_every_language_has_a_name_a_native_name_and_a_speech_code():
    assert all(lang.code and lang.name and lang.native_name for lang in LANGUAGES)
    assert all(lang.transcribe_code.startswith(lang.code + "-") for lang in LANGUAGES)
    assert len(BY_CODE) == len(LANGUAGES)


def test_the_speech_adapter_and_the_api_accept_the_same_languages():
    assert set(LANGUAGE_CODES) == set(DEFAULT_ALLOWED.split(","))
    assert set(Settings().allowed_languages.split(",")) == set(LANGUAGE_CODES)


@pytest.mark.parametrize(
    "word",
    ["வணக்கம்", "नमस्ते", "నమస్కారం", "നമസ്കാരം", "ನಮಸ್ಕಾರ", "નમસ્તે", ["ਸਤ", "ਸ੍ਰੀ", "ਅਕਾਲ"][0]],
)
def test_search_keeps_a_word_whole_in_every_supported_script(word):
    assert tokens(f"{word} friend") == [word.casefold(), "friend"]
