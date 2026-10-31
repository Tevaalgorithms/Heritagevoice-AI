"""Groups: a family, a village, a choir. The ID is made from the name so people never type one."""

import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

MAX_ID = 48
OPEN_COMMUNITY = "everyone"  # open sharing: no group; reserved, no family can take this ID


class Group(BaseModel):
    """A group as people see it: a friendly name and the ID the system uses."""

    model_config = ConfigDict(frozen=True)
    id: str
    name: str


def slugify(name: str) -> str:
    """`My family` becomes `my-family`. A name with no letters or digits gets a random ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_ID].strip("-")
    return slug or f"group-{uuid4().hex[:6]}"
