# 0004. Answers are built from verified claims, with citations added by code

**Status:** Accepted

## Context
A fluent answer can be wrong, and a missing citation or a missing "not medically validated" notice
cannot be left to a model's discretion.

## Decision
Question answering is a fixed pipeline: rewrite, route, retrieve (text, graph or both), merge,
**verify**, then write. The verifier proposes only claims that the retrieved passages support, each
tied to its passages; claims citing a passage that was not shown are discarded. The answer writer
sees only verified claims. Citations, remedy notices and disagreements between sources are added by
code. If nothing can be verified, the answer says the recordings do not cover it.

## Consequences
- Answers are sometimes cautious or short; this is intended.
- Each step can fail on its own and degrade safely (for example, graph down means text-only with a
  warning); an unverified answer is never produced.
- The pipeline has one retrieval retry and a deadline.
- Models can be changed per job in the admin portal, with fall-backs, without touching the rules.
