"""Terraform must never hold secret values: they would end up in state and plans."""

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parent.parent / "infra"
FORBIDDEN = {
    "aws_ssm_parameter resource": r'resource\s+"aws_ssm_parameter"',
    "aws_secretsmanager_secret_version": r'resource\s+"aws_secretsmanager_secret_version"',
    "random_password": r'resource\s+"random_password"',
    "sensitive variable": r"sensitive\s*=\s*true",
}


def test_no_terraform_file_creates_or_receives_a_secret():
    found = []
    for path in INFRA.rglob("*.tf"):
        text = path.read_text()
        found += [f"{path.name}: {label}" for label, rx in FORBIDDEN.items() if re.search(rx, text)]
    assert not found, found
