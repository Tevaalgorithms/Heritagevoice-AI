"""The reviewed knowledge graph in Neo4j: a rebuildable copy of the approved assertions.

Only approved assertions of published recordings are written (the caller decides). Every node and
relationship carries the community and visibility it came from, so a query can filter inside the
pattern. Relationship types come from a fixed enum, never from user text; every value is passed as
a query parameter. Replacing a recording is one transaction, and one query per relationship type
however many assertions there are. Nothing here is the authorization boundary: PostgreSQL
re-checks each result.
"""

import logging
from collections import defaultdict
from typing import Any

from app.errors import ProviderError
from app.models.records import GraphAssertion, Relation, Visibility

logger = logging.getLogger("heritagevoice.neo4j")
GRAPH = "graph"
ENTITY_KEY = "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE"
# Delete the recording's edges, then only those endpoints that no longer have any edge.
REMOVE_RECORDING = (
    "MATCH (a)-[r {recording_id: $recording_id}]->(b) "
    "WITH r, a, b DELETE r "
    "WITH collect(DISTINCT a) + collect(DISTINCT b) AS touched "
    "UNWIND touched AS e WITH DISTINCT e WHERE NOT (e)--() DELETE e"
)
EDGE_RECORDINGS = (
    "MATCH ()-[r]->() WHERE r.recording_id IS NOT NULL RETURN DISTINCT r.recording_id AS id"
)


def entity_key(community_id: str, name: str) -> str:
    """One node per name inside a community: `Amma` in two communities are two nodes."""
    return f"{community_id}:{' '.join(name.split()).casefold()}"


def _write_query(relation: Relation) -> str:
    return (
        "UNWIND $rows AS row "
        "MERGE (s:Entity {key: row.skey}) SET s.name = row.subject, s.community_id = $community_id "
        "MERGE (o:Entity {key: row.okey}) SET o.name = row.object, o.community_id = $community_id "
        f"MERGE (s)-[r:{relation.value} {{assertion_id: row.assertion_id}}]->(o) "
        "SET r.recording_id = $recording_id, r.community_id = $community_id, "
        "r.visibility = $visibility, r.segment_id = row.segment_id, r.asserted_by = row.asserted_by"
    )


def _row(assertion: GraphAssertion, community_id: str) -> dict[str, str]:
    return {
        "skey": entity_key(community_id, assertion.subject),
        "okey": entity_key(community_id, assertion.object),
        "subject": assertion.subject,
        "object": assertion.object,
        "assertion_id": assertion.id,
        "segment_id": assertion.supporting_segment_id,
        "asserted_by": assertion.asserted_by,
    }


def _by_relation(
    assertions: list[GraphAssertion], community_id: str
) -> dict[Relation, list[dict[str, str]]]:
    grouped: dict[Relation, list[dict[str, str]]] = defaultdict(list)
    for assertion in assertions:
        grouped[assertion.relation].append(_row(assertion, community_id))
    return grouped


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
        """Make the graph hold exactly these assertions for the recording, or change nothing."""
        shared: dict[str, Any] = {
            "recording_id": recording_id,
            "community_id": community_id,
            "visibility": visibility.value,
        }
        statements: list[tuple[str, dict[str, Any]]] = [
            (REMOVE_RECORDING, {"recording_id": recording_id})
        ]
        for relation, rows in _by_relation(assertions, community_id).items():
            statements.append((_write_query(relation), {**shared, "rows": rows}))
        self._transaction(statements)

    def delete_recording(self, recording_id: str) -> None:
        self._transaction([(REMOVE_RECORDING, {"recording_id": recording_id})])

    def recording_ids(self) -> list[str]:
        """Every recording that currently has edges in the graph."""
        return sorted(str(record["id"]) for record in self._run(EDGE_RECORDINGS, {}))

    def _run(self, query: str, parameters: dict[str, Any]) -> list[Any]:
        try:
            records, _, _ = self._driver.execute_query(query, parameters)
        except Exception as error:
            raise _failure(error) from error
        return list(records)

    def _transaction(self, statements: list[tuple[str, dict[str, Any]]]) -> None:
        def work(tx: Any) -> None:
            for query, parameters in statements:
                tx.run(query, parameters).consume()

        try:
            with self._driver.session() as session:
                session.execute_write(work)
        except Exception as error:
            raise _failure(error) from error


def _failure(error: Exception) -> ProviderError:
    logger.warning("graph write failed: %s", type(error).__name__)
    return ProviderError("graph write failed", code=GRAPH)
