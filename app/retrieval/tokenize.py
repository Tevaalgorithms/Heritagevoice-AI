"""Split text into word tokens for any script, including Tamil.

Python's `\\w` is not enough: Tamil vowel signs and the virama are combining marks, so a pattern
like `\\w+` cuts `வணக்கம்` into `வணக` and `கம`. Letters, combining marks and digits all belong
inside a token here. Text is normalized to NFC and case-folded so the same word always matches.
"""

import unicodedata

TOKEN_CATEGORIES = frozenset({"L", "M", "N"})


def _is_token_char(char: str) -> bool:
    return unicodedata.category(char)[0] in TOKEN_CATEGORIES


def tokens(text: str) -> list[str]:
    found: list[str] = []
    current: list[str] = []
    for char in unicodedata.normalize("NFC", text).casefold():
        if _is_token_char(char):
            current.append(char)
        elif current:
            found.append("".join(current))
            current = []
    if current:
        found.append("".join(current))
    return found
