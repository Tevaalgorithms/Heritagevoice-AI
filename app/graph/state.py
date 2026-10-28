"""Graph state excludes client-controlled authorization claims."""

from typing import TypedDict

from app.models.evidence import Claim, Evidence, Route


class WorkflowState(TypedDict, total=False):
    question: str
    route: Route
    hybrid_evidence: list[Evidence]
    graph_evidence: list[Evidence]
    evidence: list[Evidence]
    claims: list[Claim]
    answer: str
    status: str
