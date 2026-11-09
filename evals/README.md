# Release evaluation

Keep the release evaluation suite separate from the development questions. Label routes, required facts, authorized evidence IDs, paths and expected outcomes, and add verification pairs, follow-up conversations and isolation scenarios. Only the small synthetic development fixtures below are supplied.

Write versioned reports under `results/` with commit, corpus, prompt and model identifiers, per-case outcomes, aggregate denominators and latency. A passing unit-test suite is not a quality evaluation.

`uv run python -m evals.report` does this for retrieval and writes `results/published/<date>-retrieval-<index>-<commit>.json`. Each report holds the commit (and whether the tree was clean), the corpus and its size, whether it is synthetic, the kind of vector index, the models used (none yet), every case's outcome, totals with their denominators (overall, per language, per question type), latency (median and slowest), and a list of limits. Only the `published/` folder is committed, and only synthetic fixtures may be run into it. Everything else in `results/` stays git-ignored, so a run on real material can never be committed by accident. Prompt identifiers will appear once answer quality is measured.

Published so far:

| Report | What | Result |
| --- | --- | --- |
| `2026-11-09-retrieval-fake-vectors-*` | Keyword plus a fake word-based index, 28 synthetic questions, 9 languages | Found in the top 5: 23 of 24 answerable questions (0.96), mean reciprocal rank 0.89. The miss is the Tamil paraphrase `q06`. |
| `2026-11-09-retrieval-keyword-*` | Keyword search only | Same questions; compare the ranking. |

These show that search and indexing work across scripts. They say nothing about how well a real embedding model understands meaning. For that, put your Pinecone key in your shell (never in a file) and run:

```
PINECONE_API_KEY=... uv run python -m evals.report --embedding-model multilingual-e5-large
```

Only the embedding calls go to Pinecone Inference (about 130 short texts, a fraction of a cent); the index itself stays in memory and nothing is stored in your Pinecone project. The report is named `...-retrieval-real-embeddings-<commit>.json` and records the model.

## Development fixtures

`fixtures/recordings.json` (six recordings, Tamil and English) and `fixtures/questions.json` (twelve questions: 4 exact-term, 3 paraphrase, 3 relationship, 2 unsupported) are **synthetic**, written for evaluation. They are not real community material. Have a native Tamil speaker review the Tamil text and translations before treating them as ground truth. Expected sources are `recording:segment` IDs from the recordings file. `tests/test_eval_fixtures.py` checks the mix and that every expected source exists.

## LangSmith experiments

`uv run python -m evals.langsmith_eval --local` prints recall@5 and mean reciprocal rank overall and per language, with no account. Without `--local` it uploads the synthetic questions as a LangSmith dataset and records an experiment (commit, corpus and index kind are stored with it). It needs `LANGSMITH_API_KEY` in your shell, never in a file here. Only the synthetic fixtures in this folder and `app/demo_recordings.json` are ever sent.

The vector index in this harness is a fake word-based one, so it checks the plumbing and keyword search in every language. Questions that need meaning (the Tamil paraphrase `q06`) are expected to miss until a real multilingual embedding model is run through it. Answer quality and correct refusals need language-model calls and are not covered yet.
