# Release evaluation

Keep the release evaluation suite separate from the development questions. Label routes, required facts, authorized evidence IDs, paths and expected outcomes, and add verification pairs, follow-up conversations and isolation scenarios. Only the small synthetic development fixtures below are supplied.

Write versioned reports under `results/` with commit, corpus, prompt and model identifiers, per-case outcomes, aggregate denominators and latency. A passing unit-test suite is not a quality evaluation.

## Development fixtures

`fixtures/recordings.json` (six recordings, Tamil and English) and `fixtures/questions.json` (twelve questions: 4 exact-term, 3 paraphrase, 3 relationship, 2 unsupported) are **synthetic**, written for evaluation. They are not real community material. Have a native Tamil speaker review the Tamil text and translations before treating them as ground truth. Expected sources are `recording:segment` IDs from the recordings file. `tests/test_eval_fixtures.py` checks the mix and that every expected source exists.
