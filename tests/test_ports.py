import pytest

from app.fakes import FakeGraphStore, FakeTranscriber, FakeTranslator, FakeVectorStore
from app.models.transcript import Segment
from app.ports import GraphStore, Transcriber, Translator, VectorStore
from app.security.permissions import Principal


@pytest.mark.parametrize(
    ("fake", "port"),
    [
        (FakeVectorStore(), VectorStore),
        (FakeGraphStore(), GraphStore),
        (FakeTranscriber([]), Transcriber),
        (FakeTranslator(), Translator),
    ],
)
def test_fakes_satisfy_their_ports(fake, port):
    assert isinstance(fake, port)


def test_vector_search_is_filtered_by_principal(principal, evidence):
    store = FakeVectorStore()
    restricted = evidence.model_copy(
        update={"evidence_id": "ev-2", "access_groups": frozenset({"researcher"})}
    )
    store.upsert([evidence, restricted])
    hits = store.search("synthetic event", principal)
    assert [h.evidence_id for h in hits] == ["ev-1"]


def test_vector_delete_removes_results(principal, evidence):
    store = FakeVectorStore()
    store.upsert([evidence])
    store.delete(["ev-1"])
    assert store.search("synthetic", principal) == []


def test_vector_search_denies_unknown_groups(evidence):
    store = FakeVectorStore()
    store.upsert([evidence.model_copy(update={"access_groups": frozenset({"mystery"})})])
    stranger = Principal(user_id="u", groups=frozenset({"mystery"}), policy_version="v1")
    assert store.search("synthetic", stranger) == []


def test_graph_traversal_respects_hop_limit_and_principal(principal, evidence):
    near = evidence.model_copy(update={"graph_paths": (("e1", "e2"),)})
    far = evidence.model_copy(update={"evidence_id": "ev-9", "graph_paths": (("a", "b", "c"),)})
    store = FakeGraphStore([near, far])
    assert [h.evidence_id for h in store.traverse("q", principal, max_hops=2)] == ["ev-1"]


def test_translator_keeps_segment_ids_and_timing():
    segment = Segment(segment_id="s1", start_s=0.0, end_s=2.5, text="vanakkam")
    (translated,) = FakeTranslator().translate([segment], "en")
    assert (translated.segment_id, translated.start_s, translated.end_s) == ("s1", 0.0, 2.5)
    assert translated.text == "[en] vanakkam"


def test_segment_must_end_after_it_starts():
    with pytest.raises(ValueError, match="end after it starts"):
        Segment(segment_id="s1", start_s=2.0, end_s=2.0, text="x")
