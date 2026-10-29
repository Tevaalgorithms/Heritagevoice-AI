"""Guard: nothing that looks like a credential may be committed (gitleaks also runs in CI)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
}
SKIP_FILES = {"uv.lock", "requirements.txt", ".env"}  # .env is the developer's own, gitignored file
TEXT_SUFFIXES = {
    ".py",
    ".json",
    ".yml",
    ".yaml",
    ".tf",
    ".sh",
    ".md",
    ".toml",
    ".example",
    ".env",
    "",
}
PATTERNS = {
    "AWS access key id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "provider API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "LangSmith API key": re.compile(r"\b(lsv2|ls)_(pt|sk)_[A-Za-z0-9]{20,}"),
    "Pinecone API key": re.compile(r"\bpcsk_[A-Za-z0-9_]{20,}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "URL with inline password": re.compile(r"://[A-Za-z0-9_.-]+:[^@\s/${}<>'\"]{3,}@(?!localhost)"),
    "hard-coded secret assignment": re.compile(
        r"(?i)\b(password|passwd|secret|api_?key|token)\b\s*[:=]\s*[\"'][A-Za-z0-9+/_-]{12,}[\"']"
    ),
}
FORBIDDEN_FILES = ("*.tfstate", "*.tfstate.*", "*.tfvars", "tfplan", "*.tfplan", "*.pem", "*.key")


def candidate_files():
    for path in ROOT.rglob("*"):
        skipped = set(path.parts) & SKIP_DIRS or path.name in SKIP_FILES
        if path.is_file() and not skipped and path.suffix in TEXT_SUFFIXES:
            yield path


def test_no_credential_shaped_strings_are_committed():
    findings = []
    for path in candidate_files():
        if path == Path(__file__):
            continue
        text = path.read_text(errors="ignore")
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append(f"{path.relative_to(ROOT)}: {name}: {match.group(0)[:30]}")
    assert not findings, "possible secrets:\n" + "\n".join(findings)


def test_example_env_has_no_values_for_secret_names():
    for line in (ROOT / ".env.example").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#") and re.search(r"(?i)secret|password|token|key", key):
            assert value == "", key


def test_gitignore_covers_secret_files():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    for pattern in (".env", *FORBIDDEN_FILES):
        assert pattern in ignored, f"{pattern} missing from .gitignore"
