"""The knowledge graph, following the Neo4j settings saved in the admin portal.

Like the vector store, it looks at the saved address, user and password each time it is used and
builds the real connection the first time they are all present (and again if any changes). Until
Neo4j is configured it does nothing, so publishing and search keep working without it.
"""

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from neo4j import GraphDatabase

from app.adapters.neo4j_graph import Neo4jProjection
from app.models.records import GraphAssertion, Visibility
from app.ports import GraphProjection
from app.secrets import SecretReader

logger = logging.getLogger("heritagevoice.graph")


@dataclass(frozen=True)
class Neo4jConfig:
    """Everything needed to connect. Two configs are equal only if all fields match."""

    uri: str
    user: str
    password: str

    def fingerprint(self) -> tuple[str, str, str]:
        """Tells configs apart without keeping the password in a comparison or a log line."""
        return (self.uri, self.user, hashlib.sha256(self.password.encode()).hexdigest()[:12])


Builder = Callable[[Neo4jConfig], GraphProjection]


def _text(reader: SecretReader, name: str) -> str | None:
    value = reader.get(name)
    return value.get_secret_value() if value else None


def current_config(reader: SecretReader) -> Neo4jConfig | None:
    """The saved settings. None until all three exist."""
    uri, user = _text(reader, "NEO4J_URI"), _text(reader, "NEO4J_USERNAME")
    password = _text(reader, "NEO4J_PASSWORD")
    return Neo4jConfig(uri, user, password) if uri and user and password else None


def _neo4j_builder(config: Neo4jConfig) -> GraphProjection:
    projection = Neo4jProjection(
        GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    )
    projection.ensure_schema()
    return projection


class RuntimeGraphProjection:
    """A graph projection that rebuilds itself when the saved Neo4j settings change."""

    def __init__(self, reader: SecretReader, build: Builder = _neo4j_builder) -> None:
        self._reader = reader
        self._build = build
        self._built: tuple[tuple[str, str, str], GraphProjection] | None = None

    def replace_recording(
        self,
        recording_id: str,
        community_id: str,
        visibility: Visibility,
        assertions: list[GraphAssertion],
    ) -> None:
        store = self._store()
        if store is not None:
            store.replace_recording(recording_id, community_id, visibility, assertions)

    def delete_recording(self, recording_id: str) -> None:
        store = self._store()
        if store is not None:
            store.delete_recording(recording_id)

    def recording_ids(self) -> list[str]:
        store = self._store()
        return [] if store is None else store.recording_ids()

    def _store(self) -> GraphProjection | None:
        config = current_config(self._reader)
        if config is None:
            return None
        if self._built is None or self._built[0] != config.fingerprint():
            self._built = self._rebuild(config)
        return self._built[1] if self._built else None

    def _rebuild(self, config: Neo4jConfig) -> tuple[tuple[str, str, str], GraphProjection] | None:
        try:
            return config.fingerprint(), self._build(config)
        except Exception as error:  # a bad address or login: publishing keeps working
            logger.warning("Neo4j could not be set up: %s", type(error).__name__)
            return None
