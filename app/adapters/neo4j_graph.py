"""The reviewed knowledge graph in Neo4j: a rebuildable copy of the approved assertions.

Only approved assertions of published recordings are written (the caller decides). Every node and
relationship carries the community and visibility it came from, so a query can filter inside the
pattern. Relationship types come from a fixed enum, never from user text; every value is passed as
a query parameter. Nothing here is the authorization boundary: PostgreSQL re-checks each result.
"""

import logging
from typing import Any

from app.errors import ProviderError
from app.models.records import GraphAssertion, Relation, Visibility

logger = logging.getLogger("heritagevoice.neo4j")
GRAPH = "graph"
ENTITY_KEY = "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE"
REMOVE_EDGES = "MATCH ()-[r {recording_id: $recording_id}]->() DELETE r"
REMOVE_ORPHANS = "MATCH (e:Entity) WHERE NOT (e)--() DELETE e"
EDGE_RECORDINGS = (
    "MATCH ()-[r]->() WHERE r.recording_id IS NOT NULL RETURN DISTINCT r.recording_id AS id"
)


def entity_key(community_id: str, name: str) -> str:
    """One node per name inside a community: `Amma` in two communities are two nodes."""
    return f"{community_id}:{' '.join(name.split()).casefold()}"


def _write_query(relation: Relation) -> str:
    return (
        "MERGE (s:Entity {key: $skey}) SET s.name = $subject, s.community_id = $community_id "
        "MERGE (o:Entity {key: $okey}) SET o.name = $object, o.community_id = $community_id "
        f"MERGE (s)-[r:{Relation(relation).value} {{assertion_id: $assertion_id}}]->(o) "
        "SET r.recording_id = $recording_id, r.community_id = $community_id, "
        "r.visibility = $visibility, r.segment_id = $segment_id, r.asserted_by = $asserted_by"
    )


def _parameters(
    assertion: GraphAssertion, community_id: str, visibility: Visibility
) -> dict[str, Any]:
    return {
        "skey": entity_key(community_id, assertion.subject),
        "okey": entity_key(community_id, assertion.object),
        "subject": assertion.subject,
        "object": assertion.object,
        "community_id": community_id,
        "assertion_id": assertion.id,
        "recording_id": assertion.recording_id,
        "visibility": visibility.value,
        "segment_id": assertion.supporting_segment_id,
        "asserted_by": assertion.asserted_by,
    }


class Neo4jProjection:
    """Writes and removes one recording's approved assertions."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def ensure_schema(self) -> None:
        self._run(ENTITY_KEY, {})

    def replace_recording(
        self,
        recording_id: str,
        community_id: str,
        visibility: Visibility,
        assertions: list[GraphAssertion],
    ) -> None:
        """Make the graph hold exactly these assertions for the recording."""
        self.delete_recording(recording_id)
        for assertion in assertions:
            self._run(
                _write_query(assertion.relation), _parameters(assertion, community_id, visibility)
            )

    def delete_recording(self, recording_id: str) -> None:
        self._run(REMOVE_EDGES, {"recording_id": recording_id})
        self._run(REMOVE_ORPHANS, {})

    def recording_ids(self) -> list[str]:
        """Every recording that currently has edges in the graph."""
        records = self._run(EDGE_RECORDINGS, {})
        return sorted(str(record["id"]) for record in records)

    def _run(self, query: str, parameters: dict[str, Any]) -> list[Any]:
        try:
            records, _, _ = self._driver.execute_query(query, parameters)
        except Exception as error:
            logger.warning("graph write failed: %s", type(error).__name__)
            raise ProviderError("graph write failed", code=GRAPH) from error
        return list(records)
