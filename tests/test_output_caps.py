"""Every job has a ceiling on what one call may write."""

import pytest

from app.adapters.llm_runner import MAX_OUTPUT_TOKENS
from app.models.llm import ModelRole


@pytest.mark.parametrize("role", list(ModelRole))
def test_every_job_has_a_generous_output_ceiling(role):
    assert 4_000 <= MAX_OUTPUT_TOKENS[role] <= 64_000
