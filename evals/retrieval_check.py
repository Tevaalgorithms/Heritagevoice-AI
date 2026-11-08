"""Run the whole retrieval step on the evaluation fixtures and print the rank of each source.

    uv run python -m evals.retrieval_check            # keyword plus a fake word-based vector index
    uv run python -m evals.retrieval_check --keyword  # keyword search only

The fake vector index matches on shared words, so it does not measure meaning or cross-language
retrieval: use it to check the plumbing. A real measurement needs a multilingual embedding model
(see `evals.embedding_bakeoff`). Nothing here touches a real database or service.
"""

import argparse
import json
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine

from app.adapters.pinecone_store import PineconeVectorStore
from app.agents.hybrid_rag import HybridRetriever
from app.db.session import session_scope
from app.db.tables import Base
from app.evaluation import load_fixtures
from app.fakes import FakeEmbedder, FakePineconeIndex
from app.indexing import IndexDeps, index_one
from app.models.evidence import Evidence
from app.ports import VectorStore
from app.retrieval.evidence_store import hydrate
from app.retrieval_evaluation import publish_fixture, run_cases, summarize
from app.security.permissions import Principal, community_label

FIXTURES = Path(__file__).parent / "fixtures"


def _reader(recordings: list[dict]) -> Principal:
    communities = frozenset(r["community_id"] for r in recordings)
    return Principal(
        user_id="evaluator",
        groups=frozenset({"public"} | {community_label(c) for c in communities}),
        policy_version="v1",
        communities=communities,
    )


def _vector_store(engine, with_vectors: bool) -> VectorStore | None:
    if not with_vectors:
        return None

    def hydrate_for(ids: list[str], principal: Principal) -> list[Evidence]:
        with session_scope(engine) as session:
            return hydrate(session, ids, principal, "vector")

    return PineconeVectorStore(FakePineconeIndex(), FakeEmbedder(), hydrate_for, dimension=64)


@contextmanager
def retriever_for(
    recordings: list[dict], with_vectors: bool = True
) -> Iterator[Callable[[str], list[Evidence]]]:
    """Publish and index these fixtures in a throwaway database; yield `retrieve(question)`."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{tmp}/retrieval.db")
        Base.metadata.create_all(engine)
        store = _vector_store(engine, with_vectors)
        with session_scope(engine) as session:
            for recording in recordings:
                publish_fixture(session, recording)
        deps = IndexDeps(lambda: session_scope(engine), store)
        for recording in recordings:
            index_one(deps, recording["id"])
        retriever = HybridRetriever(lambda: session_scope(engine), store)
        reader = _reader(recordings)

        def retrieve(question: str) -> list[Evidence]:
            return retriever({"question": question}, reader)["hybrid_evidence"]

        try:
            yield retrieve
        finally:
            engine.dispose()


def run(with_vectors: bool = True) -> dict:
    recordings, questions = load_fixtures(FIXTURES)
    with retriever_for(recordings, with_vectors) as retrieve:
        results = run_cases(retrieve, questions)
    return {"vectors": "fake word-based" if with_vectors else "none", **summarize(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval on the fixtures")
    parser.add_argument("--keyword", action="store_true", help="keyword search only")
    args = parser.parse_args()
    print(json.dumps(run(with_vectors=not args.keyword), indent=2))


if __name__ == "__main__":
    main()
