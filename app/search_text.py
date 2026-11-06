"""Tidy what someone typed or said before it is searched.

A speech service adds full stops and sometimes writes the sounds people make while thinking
("hmm", "um"). Neither is part of what they are looking for, but a search for "பணிவு." finds
nothing when the stored word is "பணிவு". Letters, digits and the marks that belong to letters (the
vowel signs of Tamil and other scripts) are kept; everything else becomes a space.
"""

import unicodedata

KEPT = frozenset("LMN")  # letters, combining marks, numbers
JOINED = frozenset("'’‌‍")  # apostrophes and invisible joiners: remove, do not split
FILLERS = frozenset(
    {"hm", "hmm", "hmmm", "mm", "mmm", "um", "umm", "uh", "uhh", "er", "erm", "ah", "ahh", "eh"}
    | {"ம்", "ம்ம்", "ஹ்ம்", "ஆ", "ஆஹா"}
)


def _plain(char: str) -> str:
    """The character if it belongs to a word, nothing for a joiner, a space for punctuation."""
    if char in JOINED:
        return ""
    return char if unicodedata.category(char)[0] in KEPT else " "


def _without_fillers(words: list[str]) -> list[str]:
    return [word for word in words if word.casefold() not in FILLERS]


def clean_search_text(text: str, drop_fillers: bool = False) -> str:
    """The words of `text` with punctuation removed; optionally without "hmm"-style sounds."""
    words = "".join(map(_plain, text)).split()
    return " ".join(_without_fillers(words) if drop_fillers else words)
