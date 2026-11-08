"""Who a recording is credited to and where its knowledge came from.

Both are optional and given by the contributor. They are shown to readers only when the recording's
consent includes the attribution right (see `app/credits.py`); until then they stay private.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

MAX_NAME = 100
MAX_NOTE = 200
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


SYNTHETIC_NOTE = "Synthetic test recording"  # the source note that marks invented demo material


class SourceKind(StrEnum):
    """Where the knowledge in a recording came from."""

    OWN = "own"
    FAMILY = "family"
    ELDER = "elder"
    BOOK = "book"
    WEBSITE = "website"
    OTHER = "other"


class Credit(BaseModel):
    """What may be shown about a recording's origin."""

    model_config = ConfigDict(frozen=True)
    name: str | None = None
    source_kind: SourceKind | None = None
    source_note: str | None = None

    def is_empty(self) -> bool:
        return not (self.name or self.source_kind or self.source_note)


def clean_text(value: str | None, limit: int) -> str | None:
    """Plain text on one line, trimmed and cut to `limit`; None when nothing is left."""
    if value is None:
        return None
    text = " ".join(CONTROL.sub(" ", value).split())[:limit].strip()
    return text or None
