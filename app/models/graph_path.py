"""A route through the knowledge graph between things named in a question."""

from pydantic import BaseModel, ConfigDict


class GraphPath(BaseModel):
    """One path: the assertions along it, and its names and relations in reading order."""

    model_config = ConfigDict(frozen=True)
    assertion_ids: tuple[str, ...]
    steps: tuple[str, ...]  # for example ("Amma", "MENTIONS", "the well")
