"""Measure the whole retrieval step on the evaluation fixtures (task 6.6).

For each answerable question we run the real retrieval node and record the rank of the first
expected recording among the distinct recordings it returned (1 is best). The fixtures name
`recording:segment` sources; this measures at recording level, which is the unit a reader cites.
Questions with no supported answer are listed separately: returning passages for them is not wrong
here, since deciding there is not enough evidence is the verification step's job.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.repositories import (
    ConsentRepository,
    NewVersion,
    RecordingRepository,
    VersionRepository,
)
from app.models.evidence import Evidence
from app.models.records import (
    Consent,
    Recording,
    RecordingStatus,
    Right,
    Subject,
    VersionStatus,
)
from app.models.transcript import Segment

TOP = 5


@dataclass(frozen=True)
class CaseResult:
    """What retrieval returned for one question, and where the expected recording ranked."""

    question_id: str
    category: str
    language: str
    expected: tuple[str, ...]
    rank: int | None
    returned: tuple[str, ...]


def recording_of(source: str) -> str:
    """`rec-01:s1` is a segment of recording `rec-01`."""
    return source.split(":", 1)[0]


def distinct_recordings(evidence: list[Evidence]) -> list[str]:
    """The recordings in the order they first appear."""
    return list(dict.fromkeys(item.document_id for item in evidence))


def first_rank(returned: list[str], expected: set[str]) -> int | None:
    """1-based position of the first expected recording, or None if it was not returned."""
    return next((i for i, rec in enumerate(returned, start=1) if rec in expected), None)


def run_cases(
    retrieve: Callable[[str], list[Evidence]], questions: list[dict[str, Any]]
) -> list[CaseResult]:
    results = []
    for question in questions:
        returned = distinct_recordings(retrieve(question["question"]))
        expected = tuple(sorted({recording_of(s) for s in question["expected_sources"]}))
        results.append(
            CaseResult(
                question_id=question["id"],
                category=question["category"],
                language=question["language"],
                expected=expected,
                rank=first_rank(returned, set(expected)),
                returned=tuple(returned),
            )
        )
    return results


def _hit(result: CaseResult) -> bool:
    return result.rank is not None and result.rank <= TOP


def _category_report(found: list[CaseResult]) -> dict[str, Any]:
    return {
        "cases": len(found),
        "found_in_top": sum(_hit(r) for r in found),
        "ranks": {r.question_id: r.rank for r in found},
    }


def _grouped(answerable: list[CaseResult]) -> dict[str, list[CaseResult]]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for result in answerable:
        groups[result.category].append(result)
        groups["all"].append(result)
    return groups


def _unsupported_that_returned(results: list[CaseResult]) -> list[str]:
    return [r.question_id for r in results if not r.expected and r.returned]


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """Per category: how many answerable questions found their source in the top results."""
    groups = _grouped([r for r in results if r.expected])
    return {
        "top": TOP,
        "by_category": {name: _category_report(found) for name, found in sorted(groups.items())},
        "unsupported_questions_that_returned_passages": _unsupported_that_returned(results),
    }


def _segments(recording: dict[str, Any], translated: bool) -> list[Segment]:
    key = "translation" if translated else "text"
    return [
        Segment(segment_id=s["segment_id"], start_s=s["start_s"], end_s=s["end_s"], text=s[key])
        for s in recording["segments"]
        if s.get(key)
    ]


def publish_fixture(session: Session, recording: dict[str, Any]) -> None:
    """Add one fixture recording as published, with its transcript and translation approved."""
    consent = recording["consent"]
    rights = frozenset(Right(r) for r in consent["rights"])
    ConsentRepository(session).add(
        Consent(
            id=f"consent-{recording['id']}",
            community_id=recording["community_id"],
            rights=rights,
            policy_version=consent["policy_version"],
        )
    )
    RecordingRepository(session).create(
        Recording(
            id=recording["id"],
            community_id=recording["community_id"],
            uploader_id="fixture",
            language=recording["language"],
            consent_id=f"consent-{recording['id']}",
            status=RecordingStatus.PUBLISHED,
        )
    )
    versions = VersionRepository(session)
    transcript = NewVersion(
        recording["id"], Subject.TRANSCRIPT, _segments(recording, False), "system"
    )
    versions.add_draft(transcript)
    versions.set_status(recording["id"], Subject.TRANSCRIPT, 1, VersionStatus.APPROVED)
    translation = _segments(recording, True)
    if translation:
        versions.add_draft(
            NewVersion(recording["id"], Subject.TRANSLATION, translation, "system", 1)
        )
        versions.set_status(recording["id"], Subject.TRANSLATION, 1, VersionStatus.APPROVED)
