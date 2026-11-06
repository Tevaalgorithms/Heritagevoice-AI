# Vector index (Pinecone)

A rebuildable copy that makes meaning-based search possible: it finds passages that say the same
thing in different words, or in a different language. Code: `app/adapters/pinecone_store.py`. The
index is created once with `scripts/create_pinecone_index.sh`.

## Index

| Setting | Value |
| --- | --- |
| Kind | Plain (dense) vectors |
| Dimension | 1024 (`HERITAGEVOICE_EMBEDDING_DIMENSION`; an embedding of any other size is refused) |
| Metric | Cosine |
| Embeddings | Multilingual, set by `HERITAGEVOICE_EMBEDDING_MODEL` |

## What one vector looks like

```text
id        {recording_id}:{kind}:v{version}:c{chunk}     the same as evidence_chunk.evidence_id
values    1024 numbers
metadata  recording_id, version
namespace the community id (open sharing uses "everyone")
```

- **No text is stored in Pinecone.** The passage is loaded from PostgreSQL after a hit.
- **One namespace per community.** A query reads only the namespaces the caller belongs to, plus
  `everyone`. This narrows the search and keeps it fast; it is **not** the permission check. Every
  hit is loaded again from PostgreSQL and dropped unless it is approved, current, consented and
  readable by this person.
- The recording id is the ID prefix, so all of a recording's vectors can be listed and removed
  together.

## When vectors change

| Event | What happens |
| --- | --- |
| A recording is published | Its approved passages are embedded and upserted. |
| A transcript or translation is corrected and approved | The recording's old vectors are removed and the new ones added. |
| Consent is withdrawn, or the recording is revoked or removed | Its vectors are deleted. |
| Pinecone is empty, wrong or lost | Rebuild from PostgreSQL (`app/index_rebuild.py`): every published recording is indexed again and leftovers are removed. |

If Pinecone is unreachable at question time, keyword search is used and the answer carries a
warning. See the [retrieval runbook](../runbooks/retrieval.md).
