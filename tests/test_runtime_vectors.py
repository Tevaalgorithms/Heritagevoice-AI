"""The vector store follows the saved Pinecone settings and never breaks keyword search."""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.vector_setup import PineconeConfig, RuntimeVectorStore, current_config
from tests.helpers import person

DEFAULTS = Settings(_env_file=None)
READER_PERSON = person(communities=("c1",))


class Values:
    """A reader whose values the test can change."""

    def __init__(self, **values):
        self.values = values

    def get(self, name):
        value = self.values.get(name)
        return SecretStr(value) if value else None

    def is_configured(self, name):
        return self.get(name) is not None


class FakeStore:
    def __init__(self, config):
        self.config, self.upserts, self.deletes, self.searches = config, [], [], []

    def upsert(self, items):
        self.upserts.append(items)

    def delete_recording(self, recording_id, community_id):
        self.deletes.append((recording_id, community_id))

    def search(self, query, principal, limit=20):
        self.searches.append(query)
        return ["found"]


class Builder:
    def __init__(self, error=None):
        self.configs, self.error = [], error

    def __call__(self, config):
        if self.error is not None:
            raise self.error
        self.configs.append(config)
        return FakeStore(config)


CONFIGURED = {"PINECONE_API_KEY": "pc-key", "PINECONE_INDEX": "idx"}


def store_for(reader, builder=None):
    builder = builder or Builder()
    return RuntimeVectorStore(builder, reader, DEFAULTS), builder


def test_until_pinecone_is_configured_nothing_happens_and_nothing_is_built():
    store, builder = store_for(Values())
    assert store.search("q", READER_PERSON) == []
    store.upsert([])
    store.delete_recording("r1", "c1")
    assert builder.configs == []


def test_a_key_without_an_index_is_not_enough():
    store, builder = store_for(Values(PINECONE_API_KEY="pc-key"))
    assert store.search("q", READER_PERSON) == []
    assert builder.configs == []


def test_once_configured_calls_go_to_the_real_store():
    store, builder = store_for(Values(**CONFIGURED))
    assert store.search("q", READER_PERSON) == ["found"]
    store.upsert(["x"])
    store.delete_recording("r1", "c1")
    assert len(builder.configs) == 1


def test_the_store_is_built_once_while_the_settings_stay_the_same():
    store, builder = store_for(Values(**CONFIGURED))
    for _ in range(3):
        store.search("q", READER_PERSON)
    assert len(builder.configs) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"PINECONE_INDEX": "other"},
        {"PINECONE_API_KEY": "rotated-key"},
        {"EMBEDDING_MODEL": "another-model"},
        {"EMBEDDING_DIMENSION": "768"},
    ],
    ids=["index", "key", "model", "dimension"],
)
def test_a_change_to_any_saved_setting_builds_a_fresh_store(change):
    values = Values(**CONFIGURED)
    store, builder = store_for(values)
    store.search("q", READER_PERSON)
    values.values.update(change)
    store.search("q", READER_PERSON)
    assert len(builder.configs) == 2


def test_adding_the_key_later_starts_vector_search_without_a_restart():
    values = Values()
    store, builder = store_for(values)
    assert store.search("q", READER_PERSON) == []
    values.values.update(CONFIGURED)
    assert store.search("q", READER_PERSON) == ["found"]
    assert len(builder.configs) == 1


def test_a_bad_key_or_index_never_breaks_a_search_it_just_finds_nothing():
    store, _ = store_for(Values(**CONFIGURED), Builder(error=RuntimeError("bad key detail")))
    assert store.search("q", READER_PERSON) == []
    store.upsert(["x"])  # no error either


def test_defaults_come_from_the_environment_when_nothing_is_saved():
    config = current_config(Values(**CONFIGURED), DEFAULTS)
    assert (config.model, config.dimension) == ("multilingual-e5-large", 1024)


def test_saved_model_and_dimension_override_the_defaults():
    saved = Values(**CONFIGURED, EMBEDDING_MODEL="m-2", EMBEDDING_DIMENSION="768")
    config = current_config(saved, DEFAULTS)
    assert (config.model, config.dimension) == ("m-2", 768)


def test_a_dimension_that_is_not_a_number_falls_back_to_the_default():
    assert (
        current_config(Values(**CONFIGURED, EMBEDDING_DIMENSION="abc"), DEFAULTS).dimension == 1024
    )


def test_a_changed_key_makes_a_different_config_and_never_shows_in_its_repr():
    one = PineconeConfig("key-one", "i", "m", 1)
    assert one != PineconeConfig("key-two", "i", "m", 1)
    assert "key-one" not in repr(one)
