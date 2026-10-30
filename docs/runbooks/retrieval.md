# Retrieval: how a question finds passages

Segment 06 builds the step that turns a question into a short list of cited passages. It is the
node `HybridRetriever` in `app/agents/hybrid_rag.py`. It is not yet connected to the question
endpoint or the answer step (segment 09), so asking a question in the UI does not use it yet.

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
