from pydantic import SecretStr

from app.fakes import FakeGraphProjection
from app.graph_setup import RuntimeGraphProjection
from app.models.records import Visibility


class Reader:
    def __init__(self, values):
        self.values = values

    def get(self, name):
        value = self.values.get(name)
        return SecretStr(value) if value else None

    def is_configured(self, name):
        return name in self.values


FULL = {"NEO4J_URI": "neo4j+s://x", "NEO4J_USERNAME": "neo4j", "NEO4J_PASSWORD": "pw"}


def runtime(values, built):
    def build(config):
        built.append(config)
        return FakeGraphProjection()

    return RuntimeGraphProjection(Reader(values), build)


def test_until_neo4j_is_configured_nothing_happens():
    built = []
    graph = runtime({"NEO4J_URI": "neo4j+s://x"}, built)
    graph.replace_recording("r1", "c1", Visibility.COMMUNITY, [])
    graph.delete_recording("r1")
    assert (graph.recording_ids(), built) == ([], [])


def test_it_builds_once_and_again_when_the_password_changes():
    built = []
    reader = Reader(dict(FULL))
    graph = RuntimeGraphProjection(reader, lambda c: built.append(c) or FakeGraphProjection())
    graph.replace_recording("r1", "c1", Visibility.COMMUNITY, [])
    graph.replace_recording("r2", "c1", Visibility.COMMUNITY, [])
    assert len(built) == 1
    reader.values["NEO4J_PASSWORD"] = "new"
    graph.recording_ids()
    assert len(built) == 2


def test_a_setup_failure_is_swallowed_so_publishing_keeps_working():
    def broken(config):
        raise RuntimeError("secret detail")

    graph = RuntimeGraphProjection(Reader(dict(FULL)), broken)
    graph.delete_recording("r1")
    assert graph.recording_ids() == []
