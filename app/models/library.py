"""What a person asks of the Library: which recordings, in which language, read in which form."""

from dataclasses import dataclass
from enum import StrEnum

from app.models.records import HeritageKind


class LibraryView(StrEnum):
    """Which text to read: what was said in its own language, or the English translation."""

    ORIGINAL = "original"
    TRANSLATION = "translation"


@dataclass(frozen=True)
class LibraryFilter:
    """Narrows the Library. Empty fields mean "any"."""

    language: str | None = None
    kind: HeritageKind | None = None
    view: LibraryView = LibraryView.ORIGINAL
    limit: int = 20
