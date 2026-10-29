"""Timed transcript segments shared by transcription and translation."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    segment_id: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    text: str
    speaker: str | None = None

    @model_validator(mode="after")
    def _ends_after_start(self) -> "Segment":
        if self.end_s <= self.start_s:
            raise ValueError("Segment must end after it starts")
        return self
