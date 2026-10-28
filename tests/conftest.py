import hashlib

import pytest

from app.models.evidence import Evidence
from app.security.permissions import Principal


@pytest.fixture
def principal():
    return Principal(user_id="user-a", groups=frozenset({"public"}), policy_version="v1")


@pytest.fixture
def evidence():
    passage = "Synthetic event A occurred at place B."
    return Evidence(
        evidence_id="ev-1",
        document_id="doc-1",
        document_version="v1",
        chunk_id="ch-1",
        title="Synthetic source",
        locator="fixture:doc-1#ch-1",
        passage=passage,
        passage_hash=hashlib.sha256(passage.encode()).hexdigest(),
        access_groups=frozenset({"public"}),
        retrieval_methods=frozenset({"bm25"}),
    )
