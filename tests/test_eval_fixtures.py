"""The evaluation fixtures keep the shape the plan requires, and every expected source exists."""

import json
from collections import Counter
from pathlib import Path

import pytest

from app.models.records import Right

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures"


@pytest.fixture(scope="module")
def recordings():
    return json.loads((FIXTURES / "recordings.json").read_text())["recordings"]


@pytest.fixture(scope="module")
def questions():
    return json.loads((FIXTURES / "questions.json").read_text())["questions"]


def test_there_are_six_recordings_in_tamil_and_english(recordings):
    assert len(recordings) == 6
    assert {r["language"] for r in recordings} == {"ta", "en"}
    assert len({r["id"] for r in recordings}) == 6


def test_every_recording_has_valid_consent_and_ordered_timed_segments(recordings):
    valid = {right.value for right in Right}
    for recording in recordings:
        assert set(recording["consent"]["rights"]) <= valid
        starts = [s["start_s"] for s in recording["segments"]]
        assert starts == sorted(starts)
        assert all(s["end_s"] > s["start_s"] for s in recording["segments"])


def test_the_twelve_questions_have_the_required_mix(questions):
    assert Counter(q["category"] for q in questions) == {
        "exact_term": 4,
        "paraphrase": 3,
        "relationship": 3,
        "unsupported": 2,
    }


def test_expected_sources_exist_and_unsupported_questions_have_none(recordings, questions):
    known = {f"{r['id']}:{s['segment_id']}" for r in recordings for s in r["segments"]}
    for question in questions:
        assert set(question["expected_sources"]) <= known
        assert question["answerable"] == (question["category"] != "unsupported")
        assert bool(question["expected_sources"]) == question["answerable"]


def test_at_least_four_answerable_cases_are_tamil_or_cross_language(recordings, questions):
    language = {r["id"]: r["language"] for r in recordings}
    count = 0
    for q in questions:
        source_languages = {language[s.split(":")[0]] for s in q["expected_sources"]}
        count += q["answerable"] and (
            q["language"] == "ta" or q["language"] not in source_languages
        )
    assert count >= 4


def test_fixtures_are_marked_synthetic():
    for name in ("recordings.json", "questions.json"):
        assert "SYNTHETIC" in json.loads((FIXTURES / name).read_text())["_note"]
