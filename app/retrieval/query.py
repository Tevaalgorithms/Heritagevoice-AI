"""Prepare a question for search: keep what the person typed, and add safe spelling variants.

The original wording is always searched first. A variant is added only when it differs: Unicode
normalized (the same Tamil or Hindi word can arrive in more than one byte form) and with the
invisible joiner characters removed (some keyboards insert them, some texts do not have them).
Matching across scripts or accent marks (`erram` for `ērram`) is left to the meaning-based search.
"""

import unicodedata
from dataclasses import dataclass

INVISIBLE = {"\u200b", "‌", "‍", "⁠", "﻿"}  # zero-width characters


@dataclass(frozen=True)
class QueryVariants:
    """The question as typed, and the other spellings worth searching."""

    original: str
    variants: tuple[str, ...]


def _tidy(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _without_invisible(text: str) -> str:
    return "".join(char for char in text if char not in INVISIBLE)


def normalize_query(question: str) -> QueryVariants:
    """The original first, then each distinct variant, in a stable order."""
    original = question.strip()
    candidates = [original, _tidy(original), _tidy(_without_invisible(original))]
    distinct = tuple(dict.fromkeys(c for c in candidates if c))
    return QueryVariants(original=original, variants=distinct)
