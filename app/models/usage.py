"""What the Usage page shows: tokens and an estimated cost per job and model."""

from pydantic import BaseModel, ConfigDict


class UsageTotal(BaseModel):
    """All calls of one job with one model over a period."""

    model_config = ConfigDict(frozen=True)
    role: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int


class UsageLine(UsageTotal):
    """A total with its estimated cost in US dollars; None until the model has a price."""

    cost: float | None = None


class UsageSummary(BaseModel):
    """Every line plus overall totals. `cost` adds up the priced lines only."""

    model_config = ConfigDict(frozen=True)
    days: int
    lines: list[UsageLine]
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    unpriced_models: list[str]
