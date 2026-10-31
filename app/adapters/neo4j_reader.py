"""Find paths in the knowledge graph for a question, inside the reader's own scope.

Names from the question are matched to entities, then one or two hops are followed over edges the
reader may see (their own communities, or shared with every signed-in user). The scope is part of
the query pattern, not a filter afterwards. The query is fixed text with parameters; nothing from
the question is ever placed in it. A path is only a lead: the caller re-checks every edge against
PostgreSQL before anything is used.
"""

import logging
from typing import Any

from app.errors import ProviderError
from app.models.graph_path import GraphPath

logger = logging.getLogger("heritagevoice.neo4j")
GRAPH = "graph"
MIN_NAME = 2
PATHS = (
    "MATCH (e:Entity) "
    "WHERE size(e.name) >= $min_name AND toLower($question) CONTAINS toLower(e.name) "
    "AND (e.community_id IN $communities OR EXISTS { (e)-[p]-() WHERE p.visibility = 'public' }) "
    "WITH collect(e.key) AS keys "
    "MATCH path = (s:Entity)-[rels*1..2]-(:Entity) "
    "WHERE s.key IN keys "
    "AND ALL(r IN rels WHERE r.community_id IN $communities OR r.visibility = 'public') "
    "RETURN [r IN rels | r.assertion_id] AS ids, "
    "[n IN nodes(path) | n.name] AS names, [r IN rels | type(r)] AS relations "
    "LIMIT $limit"
)


def _steps(names: list[str], relations: list[str]) -> tuple[str, ...]:
    """Interleave `[A, B, C]` and `[r1, r2]` as `A, r1, B, r2, C`."""
    steps = [names[0]]
    for relation, name in zip(relations, names[1:], strict=True):
        steps.extend([relation, name])
    return tuple(steps)


class Neo4jGraphReader:
    """Reads candidate paths. Needs a read connection; writes nothing."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def paths(self, question: str, communities: frozenset[str], limit: int) -> list[GraphPath]:
        parameters = {
            "question": question,
            "communities": sorted(communities),
            "min_name": MIN_NAME,
            "limit": limit,
        }
        try:
            records, _, _ = self._driver.execute_query(PATHS, parameters)
        except Exception as error:
            logger.warning("graph read failed: %s", type(error).__name__)
            raise ProviderError("graph read failed", code=GRAPH) from error
        return [
            GraphPath(
                assertion_ids=tuple(record["ids"]),
                steps=_steps(record["names"], record["relations"]),
            )
            for record in records
        ]
