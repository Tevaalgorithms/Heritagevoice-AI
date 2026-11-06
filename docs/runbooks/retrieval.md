# Retrieval: how a question finds passages

The step that turns a question into a short list of cited passages is the node `HybridRetriever`
in `app/agents/hybrid_rag.py`. The question endpoint (`POST /v1/query`) runs it, then the
verification and answer steps (see `answering.md`).

## What it does

1. **Prepare the question** (`app/retrieval/query.py`). The question as typed is always searched.
   Extra spellings are added only when they differ: Unicode-normalized, and with invisible joiner
   characters removed. It does not transliterate or fold accents; that is left to the vector search.
2. **Two searches, up to 20 candidates each.** Keyword search (PostgreSQL full-text, Tamil-safe) for
   each spelling, and vector search when Pinecone is configured. Each search applies the reader's
   permissions inside the query, and every result passes the eligibility gate (published, consent
   valid, current approved version, the reader's community or public).
3. **Fuse** (`app/retrieval/fusion.py`). Reciprocal rank fusion with k = 60. A passage found by both
   searches is listed once, with both methods and the rank each search gave it.
4. **Select** (`app/retrieval/selection.py`). The best 5 to 8 passages, at most 2 per recording, within
   a token budget (3000, estimated from UTF-8 size, which over-counts Tamil and so is safe). The top
   passage is always kept.

If the vector search fails, the node records the warning `vector_search_unavailable` and carries on
with keyword results. Other failures are not hidden.

## Known limits

- Vector search covers a reader's own communities only. Public recordings from other communities
  are found by keyword search.
- Keyword search matches the words typed. A paraphrase with no shared words, a question in another
  language, or a different spelling of a name depends on the vector search.
- Two passages from one recording can appear together (for example its original and its English
  translation); the per-recording cap keeps it to two.

## Measuring it

```bash
uv run python -m evals.retrieval_check            # keyword plus a fake word-based vector index
uv run python -m evals.retrieval_check --keyword  # keyword only
```

It publishes the six fixture recordings into a throwaway database, runs the 10 answerable sample
questions, and prints where each expected recording ranked (1 is best). The fake vector index only
matches shared words, so a good score shows the pieces fit together; it does **not** show that
meaning or cross-language retrieval works. For that, pick and test a real multilingual embedding
model with `python -m evals.embedding_bakeoff <model>` and a Pinecone key, then repeat this check
with it.

## Connections

The **Connections** page (Explore menu; also open to visitors) lists the relationships people have
approved, each with the words in the recording that say it, where they are, and a Listen button.
It searches the names on either side of a relationship, or shows the newest if you search for
nothing.

- **Same rules as search.** A connection is shown only if its passage could be returned by a search
  for that reader: the recording is published, its consent still allows indexing, the reader belongs
  to its community or it is public, and the relationship was approved for the transcript that is
  current. A visitor sees public recordings only and is rate limited like the public Library.
- **Source of truth.** The list is read from PostgreSQL, not from Neo4j. Neo4j only helps the
  answering step find paths.
- **In answers.** A source reached through the graph shows *Connected through: a teaches b* under
  it, so a reader can see why it was chosen.
- **Credits.** The credit and date appear with a connection under the same consent rule as the
  Library.
