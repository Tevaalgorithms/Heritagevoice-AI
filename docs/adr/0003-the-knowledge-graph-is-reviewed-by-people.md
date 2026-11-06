# 0003. The knowledge graph is reviewed by people

**Status:** Accepted

## Context
Relationship questions ("how are these two families connected?") need a graph. A graph built by a
language model alone brings back the guessing that the product exists to avoid: an invented link
between two people is worse than no link.

## Decision
A model only **proposes** relationships, each tied to the exact words that say it. A person approves
or rejects each one. Only approved relationships are written to Neo4j. At question time Neo4j
suggests paths, and every edge is checked again in PostgreSQL; a path with any failing edge is
dropped whole. Relationship types come from a fixed list.

## Consequences
- The graph grows only as fast as people review it. With few reviewers it will be small.
- Confidence scores are stored but never replace review.
- A correction to a transcript invalidates the relationships that depended on it.
- Readers see the connection together with the words that say it (the Connections page).

See [schema/graph.md](../schema/graph.md).
