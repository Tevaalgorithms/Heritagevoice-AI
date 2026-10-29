"""The frontend fixtures stay valid against the typed client models, so UI work can run on them."""

import json
from pathlib import Path

import pytest

from frontend.api_client import Health, QueryResult, Readiness

FIXTURES = Path(__file__).resolve().parents[1] / "frontend" / "fixtures"


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("health.json", Health),
        ("ready_ok.json", Readiness),
        ("ready_not_ready.json", Readiness),
        ("query_answered.json", QueryResult),
        ("query_insufficient.json", QueryResult),
    ],
)
def test_fixture_matches_its_model(name, model):
    assert model.model_validate(json.loads((FIXTURES / name).read_text()))
