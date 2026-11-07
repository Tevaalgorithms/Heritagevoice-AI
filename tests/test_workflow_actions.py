"""Workflows may only use the GitHub Actions this repository allows.

Settings, Actions, General allows GitHub's own actions plus a short list. A workflow that uses
any other action is refused by GitHub before it starts (`startup_failure`), which for the deploy
workflow means nothing is deployed. If you allow another action in the repository settings, add
it here too.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
ALLOWED = {
    "aws-actions/configure-aws-credentials",
    "hashicorp/setup-terraform",
    "astral-sh/setup-uv",
}
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s@#]+)", re.MULTILINE)


def actions_used(path: Path) -> set[str]:
    return {name for name in USES.findall(path.read_text()) if not name.startswith("./")}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_a_workflow_uses_is_allowed_by_the_repository(path):
    refused = {
        name
        for name in actions_used(path)
        if not name.startswith("actions/") and name not in ALLOWED
    }
    assert not refused, f"{path.name} uses actions the repository does not allow: {sorted(refused)}"


def test_the_guard_notices_an_action_that_is_not_allowed(tmp_path):
    workflow = tmp_path / "w.yml"
    workflow.write_text(
        "steps:\n  - uses: docker/build-push-action@v6\n  - uses: actions/checkout@v4\n"
    )
    assert actions_used(workflow) == {"docker/build-push-action", "actions/checkout"}
