import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.pinecone_store import EMBED_BATCH, PineconeEmbedder, PineconeVectorStore
from app.errors import ProviderError
from app.evaluation import evaluate, load_fixtures, passages
from app.fakes import FakeEmbedder, FakePineconeIndex
from app.models.evidence import Evidence
from app.ports import Embedder, VectorStore
from app.retrieval.lexical import bm25_ranking
from tests.helpers import person

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures"


def evidence(evidence_id="r1:transcript:v1:c0", labels=("community:c1",), text="ஏற்றம் water"):
    return Evidence(
        evidence_id=evidence_id,
        document_id=evidence_id.split(":")[0],
        document_version="v1",
        chunk_id="transcript:0",
        title="t",
        locator="audio:r1?t=0-1",
        passage=text,
        passage_hash="h",
        access_groups=frozenset(labels),
        retrieval_methods=frozenset({"vector"}),
    )


def store(index=None, embedder=None, hydrate=None, dimension=64):
    index = index or FakePineconeIndex()
    embedder = embedder or FakeEmbedder()
    return PineconeVectorStore(
        index, embedder, hydrate or (lambda ids, principal: []), dimension
    ), index


def test_the_store_and_embedder_fakes_satisfy_their_ports():
    adapter, _ = store()
    assert isinstance(adapter, VectorStore)
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(PineconeEmbedder(object(), "m"), Embedder)


def test_vectors_carry_ids_and_metadata_but_no_transcript_text():
    adapter, index = store()
    adapter.upsert([evidence(text="private words here")])
    assert list(index.namespaces) == ["c1"]
    assert list(index.namespaces["c1"]) == ["r1:transcript:v1:c0"]


def test_evidence_must_belong_to_exactly_one_community():
    adapter, _ = store()
    with pytest.raises(ValueError, match="exactly one community"):
        adapter.upsert([evidence(labels=("public",))])
    with pytest.raises(ValueError, match="exactly one community"):
        adapter.upsert([evidence(labels=("community:a", "community:b"))])


def test_an_embedding_of_the_wrong_size_is_refused():
    adapter, index = store(dimension=32)
    with pytest.raises(ProviderError) as error:
        adapter.upsert([evidence()])
    assert error.value.code == "index"
    assert index.namespaces == {}


class BrokenIndex(FakePineconeIndex):
    def upsert(self, vectors, namespace):
        raise RuntimeError("provider detail with secrets")

    def list(self, prefix, namespace):
        raise RuntimeError("provider detail with secrets")


def test_provider_failures_become_safe_errors():
    adapter, _ = store(index=BrokenIndex())
    for call in (
        lambda: adapter.upsert([evidence()]),
        lambda: adapter.delete_recording("r1", "c1"),
    ):
        with pytest.raises(ProviderError) as error:
            call()
        assert error.value.code == "index"
        assert "secrets" not in str(error.value)


def test_delete_recording_uses_the_recording_prefix_only():
    adapter, index = store()
    adapter.upsert(
        [
            evidence("r1:transcript:v1:c0"),
            evidence("r10:transcript:v1:c0"),
            evidence("r1:translation:v1:c0"),
        ]
    )
    adapter.delete_recording("r1", "c1")
    assert list(index.namespaces["c1"]) == ["r10:transcript:v1:c0"]
    adapter.delete_recording("r1", "c1")  # safe to repeat


def test_large_uploads_are_embedded_in_batches():
    embedder = FakeEmbedder()
    adapter, index = store(embedder=embedder)
    adapter.upsert([evidence(f"r1:transcript:v1:c{i}") for i in range(EMBED_BATCH * 2 + 1)])
    assert embedder.passage_calls == 3
    assert index.count("c1") == EMBED_BATCH * 2 + 1


def test_search_does_nothing_without_communities_or_words():
    embedder = FakeEmbedder()
    adapter, _ = store(embedder=embedder)
    assert adapter.search("anything", person(communities=())) == []
    assert adapter.search("   ", person()) == []


def test_search_hands_candidates_to_postgres_and_keeps_its_order_and_limit():
    seen = {}

    def hydrate(ids, principal):
        seen["ids"] = ids
        return [evidence(i) for i in ids]

    adapter, _ = store(hydrate=hydrate)
    adapter.upsert(
        [
            evidence("r1:transcript:v1:c0", text="water"),
            evidence("r2:transcript:v1:c0", text="rain"),
        ]
    )
    found = adapter.search("water", person(), limit=1)
    assert [e.evidence_id for e in found] == ["r1:transcript:v1:c0"]
    assert seen["ids"][0] == "r1:transcript:v1:c0"


def test_object_style_query_responses_are_understood():
    class ObjectIndex(FakePineconeIndex):
        def query(self, vector, top_k, namespace):
            matches = super().query(vector, top_k, namespace)["matches"]
            return SimpleNamespace(matches=[SimpleNamespace(**m) for m in matches])

    adapter, _ = store(index=ObjectIndex(), hydrate=lambda ids, p: [evidence(i) for i in ids])
    adapter.upsert([evidence(text="water")])
    assert len(adapter.search("water", person())) == 1


class FakePineconeClient:
    def __init__(self):
        self.calls = []
        self.inference = SimpleNamespace(embed=self._embed)

    def _embed(self, model, inputs, parameters):
        self.calls.append((model, len(inputs), parameters["input_type"], parameters["truncate"]))
        return [{"values": [float(len(text)), 0.0]} for text in inputs]


def test_pinecone_embeddings_use_passage_and_query_input_types():
    client = FakePineconeClient()
    embedder = PineconeEmbedder(client, "multilingual-e5-large")
    assert len(embedder.embed_passages(["a"] * (EMBED_BATCH + 1))) == EMBED_BATCH + 1
    assert embedder.embed_query("hello") == [5.0, 0.0]
    assert client.calls == [
        ("multilingual-e5-large", EMBED_BATCH, "passage", "END"),
        ("multilingual-e5-large", 1, "passage", "END"),
        ("multilingual-e5-large", 1, "query", "END"),
    ]


def test_bm25_ranks_by_shared_rare_words_and_ignores_non_matches():
    docs = {
        "a": ["water", "well", "well"],
        "b": ["water", "rain"],
        "c": ["songs", "harvest"],
    }
    assert bm25_ranking(["well"], docs) == ["a"]
    assert bm25_ranking(["water", "well"], docs) == ["a", "b"]
    assert bm25_ranking(["zzz"], docs) == []
    assert bm25_ranking([], docs) == []
    assert bm25_ranking(["water"], {}) == []


def test_bm25_ties_break_by_id_for_a_stable_order():
    docs = {"b": ["x"], "a": ["x"]}
    assert bm25_ranking(["x"], docs) == ["a", "b"]


def test_the_bakeoff_scores_questions_in_both_languages():
    recordings, questions = load_fixtures(FIXTURES)
    report = evaluate(FakeEmbedder(), recordings, questions)
    assert report["k"] == 5
    assert report["recall_at_k"]["exact_term/ta"] == 1.0
    assert report["cases"]["all"] == 10  # the two unsupported questions are not scored
    assert 0.0 <= report["mrr"] <= 1.0
    json.dumps(report, ensure_ascii=False)


def test_each_segment_is_indexed_in_both_languages_when_translated():
    recordings, _ = load_fixtures(FIXTURES)
    sources = [s for s, _ in passages(recordings)]
    assert sources.count("rec-01:s1") == 2  # Tamil text and English translation
    assert sources.count("rec-04:s1") == 1  # English recording: translation equals the text
