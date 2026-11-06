# 0001. PostgreSQL is the source of truth; Pinecone and Neo4j are rebuildable copies

**Status:** Accepted

## Context
Three stores each do one thing well: PostgreSQL for records, consent and keyword search; Pinecone
for meaning-based search; Neo4j for relationship paths. If all three held the truth, they could
disagree, and a withdrawn consent might still be honoured by one of them.

## Decision
PostgreSQL holds every fact and every permission. Pinecone and Neo4j receive only approved
material, copied from PostgreSQL, and hold nothing that cannot be rebuilt. Every hit from either is
loaded again from PostgreSQL and dropped if it is no longer approved, current, consented and
readable by the asker. Pinecone stores no text.

## Consequences
- Withdrawing consent or replacing a version is one write in PostgreSQL, followed by cleanup of the
  copies; even if cleanup is late, the re-check hides the stale hit.
- Losing Pinecone or Neo4j loses nothing: `app/index_rebuild.py` and the graph projection restore
  them. Only PostgreSQL needs backups.
- Search is slightly slower, because each hit costs one database lookup. We accept that for safety.
- The product still works with PostgreSQL alone (keyword search, text answers).

See [schema/](../schema/README.md).
