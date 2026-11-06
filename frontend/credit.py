"""Credit and source in the words readers see. Everything a contributor typed is shown as plain
text: markdown characters are escaped, so a name or a note can never add formatting or a link."""

import re
from datetime import date

SOURCE_LABELS = {
    "own": "Their own knowledge or experience",
    "family": "Told by a grandparent or family elder",
    "elder": "Told by a community elder or teacher",
    "book": "From a book or publication",
    "website": "From a website",
    "other": "Another source",
}
NOT_GIVEN = "Not given"
UPLOAD_CHOICES = {NOT_GIVEN: "", **{label: key for key, label in SOURCE_LABELS.items()}}
MARKDOWN = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<])")


def plain(text: str) -> str:
    """The text with markdown characters escaped, for use in a caption."""
    return MARKDOWN.sub(r"\\\1", text)


def long_date(iso: str) -> str:
    """`2026-11-05` as `5 Nov 2026`; anything else is shown as it is."""
    try:
        day = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{day.day} {day:%b %Y}"


def source_phrase(kind: str | None, note: str | None) -> str:
    """Where the knowledge came from, such as `From a book or publication: title and author`."""
    parts = [SOURCE_LABELS.get(kind or ""), note]
    return ": ".join(part for part in parts if part)


def origin_line(added: str, name: str | None, kind: str | None, note: str | None) -> str:
    """One caption: who to thank, where it came from, and when it was added."""
    parts = []
    if name:
        parts.append(f"Shared by {name}")
    source = source_phrase(kind, note)
    if source:
        parts.append(source)
    if added:
        parts.append(f"Added {long_date(added)}")
    return plain(" · ".join(parts))
