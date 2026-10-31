"""The knowledge graph, following the Neo4j settings saved in the admin portal.

Until the address, user and password are all saved it does nothing, so publishing and search keep
working without Neo4j. Saving them in the portal needs no redeploy (see `RuntimeStore`).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from neo4j import GraphDatabase

from app.adapters.neo4j_graph import Neo4jProjection
from app.adapters.neo4j_reader import Neo4jGraphReader
from app.models.records import GraphAssertion, Visibility
from app.ports import GraphProjection, GraphReader
from app.runtime_store import RuntimeStore
from app.secrets import SecretReader, secret_text


@dataclass(frozen=True)
class Neo4jConfig:
    """Everything needed to connect. The password never shows in a repr or a log line."""

    uri: str
    user: str
    password: str = field(repr=False)


Builder = Callable[[Neo4jConfig], GraphProjection]


def current_config(reader: SecretReader) -> Neo4jConfig | None:
    """The saved settings. None until all three exist."""
    uri, user = secret_text(reader, "NEO4J_URI"), secret_text(reader, "NEO4J_USERNAME")
    password = secret_text(reader, "NEO4J_PASSWORD")
    return Neo4jConfig(uri, user, password) if uri and user and password else None


def _driver(config: Neo4jConfig) -> Any:
    return GraphDatabase.driver(config.uri, auth=(config.user, config.password))


def _neo4j_builder(config: Neo4jConfig) -> GraphProjection:
    projection = Neo4jProjection(_driver(config))
    projection.ensure_schema()
    return projection


class _NoGraph:
    """Stands in until Neo4j is configured: writes are skipped and nothing is stored."""

    def replace_recording(
        self,
        recording_id: str,
        community_id: str,
        visibility: Visibility,
        assertions: list[GraphAssertion],
    ) -> None:
        return None

    def delete_recording(self, recording_id: str) -> None:
        return None

    def recording_ids(self) -> list[str]:
        return []


class RuntimeGraphProjection:
    """A graph projection that follows the saved Neo4j settings."""

    def __init__(self, reader: SecretReader, build: Builder = _neo4j_builder) -> None:
        self._store = RuntimeStore(lambda: current_config(reader), build, "Neo4j")

    def replace_recording(
        self,
        recording_id: str,
        community_id: str,
        visibility: Visibility,
        assertions: list[GraphAssertion],
    ) -> None:
        self._graph().replace_recording(recording_id, community_id, visibility, assertions)

    def delete_recording(self, recording_id: str) -> None:
        self._graph().delete_recording(recording_id)

    def recording_ids(self) -> list[str]:
        return self._graph().recording_ids()

    def _graph(self) -> GraphProjection:
        return self._store.get() or _NoGraph()


class RuntimeGraphReader:
    """Finds graph paths with the saved Neo4j settings. `get()` is None until they are saved."""

    def __init__(self, reader: SecretReader) -> None:
        self._store: RuntimeStore[Neo4jConfig, GraphReader] = RuntimeStore(
            lambda: current_config(reader),
            lambda config: Neo4jGraphReader(_driver(config)),
            "Neo4j",
        )

    def get(self) -> GraphReader | None:
        return self._store.get()

    def enabled(self) -> bool:
        return self.get() is not None
