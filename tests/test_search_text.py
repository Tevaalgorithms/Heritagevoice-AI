"""Search text is tidied: punctuation and 'hmm' go, the letters of every script stay."""

import pytest

from app.search_text import clean_search_text


@pytest.mark.parametrize(
    ("typed", "cleaned"),
    [
        ("பணிவு.", "பணிவு"),  # the full stop a speech service adds
        ("  பணிவு!?  ", "பணிவு"),
        ("humility, a place; a song", "humility a place a song"),
        ("elder's", "elders"),  # an apostrophe joins, it does not split
        ("யானைக்கும்  அடி\tசறுக்கும்.", "யானைக்கும் அடி சறுக்கும்"),
        ("rice-harvest (song)", "rice harvest song"),
        ("100%", "100"),
        ("", ""),
        ("?!...", ""),
    ],
)
def test_punctuation_is_removed_and_words_are_kept(typed, cleaned):
    assert clean_search_text(typed) == cleaned


def test_the_marks_that_belong_to_letters_are_kept():
    """Tamil vowel signs and the dot above are combining marks: dropping them changes the word."""
    assert clean_search_text("கற்றது.") == "கற்றது"
    assert clean_search_text("பொன்னம்மா") == "பொன்னம்மா"
    assert clean_search_text("நல்லூர்,") == "நல்லூர்"


def test_invisible_joiners_do_not_split_a_word():
    assert clean_search_text("க்‍ஷ") == "க்ஷ"


@pytest.mark.parametrize(
    ("said", "words"),
    [
        ("Hmm... பணிவு.", "பணிவு"),
        ("um, humility", "humility"),
        ("Uh hmm Humility, uh.", "Humility"),
        ("ம்ம் பணிவு", "பணிவு"),
        ("hmmm", ""),
    ],
)
def test_sounds_made_while_thinking_are_dropped_from_spoken_words(said, words):
    assert clean_search_text(said, drop_fillers=True) == words


def test_typed_text_keeps_a_word_that_looks_like_a_filler():
    assert clean_search_text("Hmm", drop_fillers=False) == "Hmm"
