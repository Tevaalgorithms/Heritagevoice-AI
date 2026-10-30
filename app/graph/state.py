"""Graph state excludes client-controlled authorization claims."""

from typing import Any, TypedDict

from app.models.evidence import Claim, Evidence, Route
from app.models.job import JobStatus
from app.models.records import Consent
from app.models.transcript import Segment

StateUpdate = dict[str, Any]
"""A partial state returned by a graph node."""


class WorkflowState(TypedDict, total=False):
    """What the question-answering graph carries between steps."""

    question: str
    route: Route
    hybrid_evidence: list[Evidence]
    graph_evidence: list[Evidence]
    evidence: list[Evidence]
    claims: list[Claim]
    answer: str
    citations: list[Evidence]
    status: str


class PreservationState(TypedDict, total=False):
    """What the recording-processing graph carries between steps."""

    recording_id: str
    consent: Consent
    language: str
    audio_key: str
    segments: list[Segment]
    translations: list[Segment]
    status: JobStatus
    error: str
