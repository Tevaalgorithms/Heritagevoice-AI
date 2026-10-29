# HeritageVoice AI — MVP Build TODO

Source: the Team 16 *HeritageVoice AI Development Plan* (12 segments, kept outside the repository), adapted to **LangGraph + LangChain + LangSmith + Pinecone + Neo4j**.
Deployment resources and decisions: [`docs/architecture/MVP_Deployment_Resources.md`](../architecture/MVP_Deployment_Resources.md).

Legend: `[ ]` open · `[x]` done · **Gate** = must pass before the next phase · Owners: A backend/agents, B retrieval/data, C frontend, D quality.

## Build order at a glance

```text
Phase 0   Tooling and standards            lint, complexity gates, CI, dependencies, ports + fakes
Phase 0B  Walking skeleton                 one fixture runs upload → review → ask → cited answer, all fakes
Phase 1   Foundation (01–03)               app setup, records + permissions + Cognito, upload + ASR
          └─ Deploy Stage 1                thin slice live on AWS (auth, DB, S3, health checks)
Phase 2   Review + Hybrid RAG (04–06)      translate/approve, build indexes, retrieve + fuse
          ├─ (in parallel if staffed) 07   graph build only needs 04
Phase 3   GraphRAG + workflow (07–09)      reviewed graph, graph retrieval, verified answers
Phase 4   Experience + delivery (10–12)    question UI + playback, validation, handover
```

Rules of thumb: replace fakes with real providers **one at a time** behind the same ports; deploy early and often; every access rule gets a failing test first.

## Working rules (apply to every task)

**What we're doing:** the habits that keep the code small, safe and replaceable.

- **Complexity:** each function has cyclomatic complexity ≤ 5. Use guard clauses, dispatch tables and small pure functions. CI fails above this.
- **Ports and adapters:** agents depend on `Protocol`s (`VectorStore`, `GraphStore`, `Transcriber`, `Translator`). Vendors (Pinecone, Postgres, AWS) live only in adapter modules.
- **Security:** default-deny. Authorization comes from the server-side `Principal`, never from model output or client input. No secrets, no restricted data in Git, prompts, logs or traces (`AGENTS.md`).
- **Tests first for every rule in the plan** that says "fail", "deny", "exclude" or "abstain".
- **Before finishing any task:** `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
- One small PR per checkbox group. Do not mix refactors with features.

---

## Phase 0 — Tooling and standards

**What we're doing:** set up the guardrails before writing features: strict lint and complexity limits, CI, the dependency swap (Qdrant out, Pinecone in), and the interfaces with in-memory fakes so everything later can be tested without the network.

- [ ] **0.1** In `pyproject.toml` add Ruff rules `C90`, `PL`, `SIM`, `RET`, `N`, `PT`, with `[tool.ruff.lint.mccabe] max-complexity = 5` and `[tool.ruff.lint.pylint] max-args = 4, max-branches = 5, max-statements = 20, max-returns = 3`.
- [ ] **0.2** Add dev dependencies `xenon` and `radon`; add a CI step `xenon --max-absolute A --max-modules A --max-average A app ingestion frontend`.
- [ ] **0.3** Add `mypy` (strict on `app/`) as a CI step. Fix scaffold typing gaps (for example `build_workflow(checkpointer=None)`).
- [ ] **0.4** Replace Qdrant with Pinecone: remove `qdrant-client`; keep `neo4j`; add `pinecone`, `langchain`, `langchain-core`, `langchain-pinecone`, `langchain-neo4j`, `pyjwt[crypto]`, an LLM package (for example `langchain-anthropic`), `sqlalchemy` (or `psycopg` repositories) and `alembic`. Run `uv lock` and regenerate `requirements.txt`.
- [ ] **0.5** Remove the `qdrant` service from `docker-compose.yml`; keep `postgres` (no pgvector needed, vectors go to Pinecone) and `neo4j` for local development. Update README technology table.
- [ ] **0.6** Add new settings to `.env.example` with empty values (`PINECONE_API_KEY`, `PINECONE_INDEX`, `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `NEO4J_URI`, `NEO4J_READ_USER`, `NEO4J_READ_PASSWORD`, `NEO4J_WRITE_USER`, `NEO4J_WRITE_PASSWORD`, `HERITAGEVOICE_DATABASE_URL`, `HERITAGEVOICE_AUDIO_BUCKET`, LLM key). Extend `tests/test_no_secrets_in_repo.py` if new patterns are needed.
- [ ] **0.7** Refactor `app/graph/workflow.py`: move the nested closures (`hybrid`, `graph`, `safe_merge`, `stop`) to module-level node factories so each node is independently testable, and replace the lambdas with named router functions.
- [ ] **0.8** Add `app/ports.py` with the `Protocol` definitions and an in-memory fake for each, used by tests.
- [ ] **0.9** Add a PR template checklist: complexity, tests, no secrets, no restricted data.

**Gate:** CI runs ruff (with complexity), xenon, mypy, pytest and gitleaks, all green on the existing scaffold.

---

## Phase 0B — Walking skeleton

**What we're doing:** prove the whole shape works end to end with fakes before building anything real. One fixture recording goes through upload, review, indexing, a question and a cited answer, using only in-memory ports and a fake model. This exposes wiring mistakes early and gives every later task a working harness.

- [ ] **S1** Define the shared models and state: `Evidence`, `Principal`, `PreservationState`, `WorkflowState`, job states (from tasks 1.3, 2.1, 9.1 in their minimal form).
- [ ] **S2** Minimal preservation graph with fake ports (fake ASR, fake translator): `queued → transcribing → translating → review` (agent A1 skeleton).
- [ ] **S3** Minimal question graph with fake retrievers and fake model: supervisor → retrieval → merge → verify → answer (builds on the existing scaffold).
- [ ] **S4 (was A9)** End-to-end test: fixture upload → approve → index (in-memory) → ask → cited answer. Assert no node receives data outside the principal's scope, and that a draft or revoked item never appears.
- [ ] **S5** Local run script (`scripts/` or a `make`-style command) that executes S4 and prints the cited answer.

**Gate:** S4 passes in CI with fakes only, and the first real adapter can replace a fake without changing any agent code.

---

## Agent development (reference; built inside the phases noted)

**What we're doing:** define the eight agents once, so every phase builds them the same way. This section is a catalog and a rule set. Its tasks are scheduled inside Phases 1–3, and its gate is at the end of Phase 3.

Source: the *Project Architecture* document, section 2. Eight agents across **two LangGraph graphs**:

- **Preservation graph** (runs in the worker): ingestion supervisor → transcription → translation → cultural context → knowledge-graph extraction. Ends at human review.
- **Question graph** (runs in the API): query supervisor → research/retrieval (Hybrid RAG + GraphRAG) → evidence merger → verification → answer.

Not every step needs an LLM. ASR, search, permission checks and audio processing stay deterministic tools.

### Rules for every agent

- [ ] **A0.1** One module per agent in `app/agents/`; the public entry point is a single node function `(state) -> dict` (a state update) with complexity ≤ 5. Logic lives in small pure helpers.
- [ ] **A0.2** Each agent has typed input and output Pydantic models. LLM calls use LangChain structured output (`prompt | model.with_structured_output(Model)`); free-text parsing is not allowed.
- [ ] **A0.3** Prompts live in `app/agents/prompts/` as versioned templates, not inline strings. Prompt text never contains secrets or restricted material beyond the permitted evidence passed in.
- [ ] **A0.4** The model name, temperature, timeout and max retries come from `Settings`. Every LLM call has a timeout and bounded retries; failures become explicit warnings or `failed` job states, never silent fallbacks.
- [ ] **A0.5** Agents receive evidence only after the permission filter. They never receive a user ID, role or community from model output; the `Principal` is injected by the wiring code.
- [ ] **A0.6** Every agent has: a unit test with a fake model (no network), a contract test for its output model, and a LangSmith evaluator (below).
- [ ] **A0.7** LangSmith: tag runs with `agent`, `graph`, `trace_id` and `prompt_version`. Inputs and outputs stay hidden until redaction exists.
- [ ] **A0.8** Shared `AgentError` types (`ProviderTimeout`, `InvalidOutput`, `NotPermitted`) mapped to safe API errors that never echo prompts or private excerpts.

### The eight agents

| # | Agent | Graph | LangChain / LangGraph building blocks | Output model | Must never | Evaluator | Built in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Preservation Supervisor** | Preservation | LangGraph `StateGraph` with Postgres checkpointer; conditional edges by stage and failure | `ProcessingPlan` (next stage, retry or fail) | Skip human review, publish content | Stage-transition tests for every failure path | Phase 0B skeleton, Phase 1 (03) |
| 2 | **Transcription Agent** | Preservation | ASR adapter (tool) + chain that proposes fixes for low-confidence spans using permitted context | `DraftTranscript` (segments with IDs, timestamps, flags) | Change timestamps or invent speech; use content with AI processing prohibited | Word-error rate on the fixture, timestamp validity | Phase 1 (03) |
| 3 | **Translation Agent** | Preservation | Runnable chain with glossary lookup tool | `TranslationDraft` (linked to segment and version, glossary notes) | Translate when translation consent is missing; drop cultural terms | Human-rated sample, glossary-term retention | Phase 2 (04) |
| 4 | **Cultural Context Agent** | Preservation | Hybrid RAG retriever tool over **already approved** evidence in the same community | `ContextAnnotation` list (each linked to a source segment) | Cite unapproved or other-community material; present a guess as fact | Every annotation resolves to an authorized segment | Phase 3 (after 06, before 07 publishes) |
| 5 | **Knowledge Graph Agent** | Preservation | Structured-output extraction chain; enum-constrained node and relation types | `CandidateAssertion` list (pending review, with supporting segment) | Set `approved`, or let confidence replace review | Precision/recall on the two-hop fixture | Phase 3 (07) |
| 6 | **Research/Retrieval Agent** | Question | Query supervisor (route) + query decomposition chain; tools: Hybrid RAG, GraphRAG | `RetrievalPlan` (route, sub-queries, branches) | Choose or widen the permission scope | Route accuracy on the 12 questions | Phase 2–3 (06, 08, 09) |
| 7 | **Verification Agent** | Question | Claim-extraction chain + deterministic citation validator; retry counter in state | `VerificationResult` (supported, unsupported, conflicts, retry flag) | Retry more than once; pass unsupported claims | Both unsupported questions abstain; claim grounding rate | Phase 3 (09) |
| 8 | **Answer Agent** | Question | Synthesis chain over verified evidence, with a final deterministic gate | `Answer` (status, text, citations, warnings, uncertainty) | Add facts without a citation; cite stale or unauthorized sources | Citation validity, language match, abstention | Phase 3 (09) |

### Agent tasks

- [ ] **A1** Ingestion supervisor: define `PreservationState` and the preservation graph; stages `queued → transcribing → translating → context → extracting → review`; one failure edge per stage. Persist with the Postgres checkpointer. (skeleton in S2; real version with 3.3)
- [ ] **A2** Transcription agent: wrap the `Transcriber` port; add the low-confidence-span resolver chain; validator rejects overlapping or out-of-range segments. (3.4)
- [ ] **A3** Translation agent: see 4.1; add the glossary tool and the consent guard as a pure `can_translate(principal, recording)` function. (4.1)
- [ ] **A4** Cultural context agent: build as a read-only tool user over approved Hybrid RAG results; output stored as annotations that need reviewer approval before publication. (after 06)
- [ ] **A5** Knowledge graph agent: see 7.2; add alias candidates and temporal context to the output model. (7.2–7.3)
- [ ] **A6** Query supervisor and research agent: classify route (`hybrid`, `graph`, `both`, `clarify`, `refuse`), detect language, extract entities, decompose multi-part questions; run both retrieval branches in parallel. (6.1, 9.2, 9.3)
- [ ] **A7** Verification agent: claim extraction, coverage check against the question, conflict detection across communities and periods, translation fidelity check; one retry then abstain. (9.5)
- [ ] **A8** Answer agent: synthesis with timestamps and uncertainty; final gate re-validates citations, source versions and permissions immediately before delivery. (9.6)
- [ ] **A9** Full-system run: repeat the S4 end-to-end test with the real adapters swapped in one by one. (Phase 3 gate)
- [ ] **A10** LangSmith: create the dataset and evaluator for each agent **as that agent is built** (inputs are IDs and fixtures only), and run them in CI on prompt changes.

---

## Phase 1 — Foundation

**What we're doing:** build the base everything else sits on: a runnable app, the data model with consent and role-based permissions (Cognito), and audio upload with transcription. Nothing AI-heavy yet; the focus is safe access and a draft transcript that stays hidden until reviewed.

### 01 Set up the application (A, C)

**Goal:** another contributor can start the web app, API and worker from the guide.

- [ ] 1.1 Create `app/db/` (engine, session, repositories) and Alembic migrations folder; add a `worker` entry point (`python -m app.worker`).
- [ ] 1.2 Extend `Settings` with database, bucket, Pinecone and LLM settings (`SecretStr` for secrets; never serialized).
- [ ] 1.3 Add a job status model (`queued, processing, review, published, failed`) and a trace ID middleware that sets one ID per request and passes it to logs and LangSmith metadata.
- [ ] 1.4 `/health` (process alive) and `/ready` (reports each **configured** dependency: Postgres and bucket now; Pinecone is added in 5.3 and Neo4j in 7.1, and an unconfigured service is skipped, not failed). Each dependency check is its own small function registered in a list.
- [ ] 1.5 Frontend: navigation (Upload, Review, Ask) and a typed API client (`httpx` + Pydantic models) with loading and configuration-error states.
- [ ] 1.6 Write `docs/runbooks/setup.md`: start web app, API and worker from a clean clone.

**Gate:** another contributor starts all three processes from the guide.

### 02 Define records, roles and permissions (A policy, B data)

**Goal:** decide who may do what, and make unauthorized actions fail before any AI provider is called.

Note: local runs use the dev token behind the same `Principal` dependency (non-production only), so Phases 1–2 are not blocked while Cognito is being set up.

- [ ] 2.1 Pydantic and SQL models: `Recording`, `Segment`, `TranscriptVersion`, `TranslationVersion`, `Consent`, `ReviewDecision`, `GraphAssertion`.
- [ ] 2.2 Separate consent rights: playback, AI processing, translation, indexing, summarization, attribution; add revocation and `policy_version`.
- [ ] 2.3 Identity with **Amazon Cognito** (deployment doc, section 3): one user pool, groups `member`, `reviewer`, `admin`, PKCE app client, TOTP MFA, self-sign-up off. Define it in Terraform.
- [ ] 2.3a Postgres tables `app_user` (sub, role, status) and `community_member` (user, community, role) with migrations.
- [ ] 2.3b `app/security/jwt.py`: verify the access token (JWKS cache, `iss`, `token_use`, `client_id`, `exp`); reject ID tokens. One small function per check.
- [ ] 2.3c FastAPI dependency that builds the server-side `Principal` from the verified token plus `app_user` and `community_member`; deny disabled or unknown users. Replace the dev token outside local runs.
- [ ] 2.3d Role/action permission table (`dict[Action, set[Role]]`) feeding `authorize()`; reviewers cannot approve their own uploads; admin has no content access.
- [ ] 2.3e Admin endpoints: invite user, set role and community membership, disable user (also Cognito global sign-out). Audit-log every change without content.
- [ ] 2.3f Streamlit sign-in: confirm how to obtain the access token (server-side OIDC flow if `st.login` does not expose it); keep tokens in server-side session state only.
- [ ] 2.3g Tests from deployment doc section 3.6 (expired, wrong issuer/client, ID token, disabled user, 403s, self-approval, membership change).
- [ ] 2.4 Extend `app/security/permissions.py` into a pure `authorize(principal, action, resource) -> Decision` using a dispatch table per action.
- [ ] 2.5 Freeze API schemas (OpenAPI snapshot test) and publish frontend fixtures.
- [ ] 2.6 Prepare 6 approved recordings or fixtures and the 12 evaluation questions (4 exact-term, 3 paraphrase, 3 relationship, 2 unsupported; at least 4 Tamil or cross-language) in `evals/`.
- [ ] 2.7 Tests: cross-community access, forged reviewer actions, revoked consent, AI-prohibited content. All must fail **before** any provider call.

**Gate:** unauthorized operations fail before provider calls, retrieval results or private content are exposed.

### 03 Upload and transcribe audio (A backend, C interface)

**Goal:** a consented recording becomes a timed draft transcript that stays out of search until a human reviews it.

- [ ] 3.1 `POST /v1/recordings`: validate type, size, duration, language, community and processing consent (one validator function per rule, composed in a list).
- [ ] 3.2 `AudioStore` adapter for S3 (private, SSE-KMS) with a local-filesystem fake for tests.
- [ ] 3.3 Idempotent ingestion job (idempotency key unique constraint) with bounded retries and safe error codes. `GET /v1/jobs/{id}`.
- [ ] 3.4 `Transcriber` adapter (Amazon Transcribe or Whisper) producing segments with stable IDs, speaker refs and valid timestamps; validator rejects overlapping or out-of-range segments.
- [ ] 3.5 Frontend: upload with progress, transcript editor, click-segment-to-seek audio, error recovery.
- [ ] 3.6 Draft transcripts are stored with `status = draft` and excluded from every search path (test it).

**Gate:** one real consented recording produces a timed draft transcript that stays out of search until review.

### Phase 1 exit — deploy the thin slice

**What we're doing:** put the foundation on AWS now (Deployment Stage 1 below), so infrastructure problems appear early instead of at the end.

**Gate:** sign-in with MFA, upload, draft transcript and `/ready` all work on the deployed environment.

---

## Phase 2 — Review and Hybrid RAG

**What we're doing:** turn draft transcripts into trusted, searchable knowledge. Humans translate-check and approve content, then we index it two ways (keyword and meaning) and combine the results. Set up LangSmith before 6.6 so retrieval quality is measured from the start.

If you have more than one contributor, 07 (graph build, Phase 3) only needs 04 and can start in parallel with 05–06.

### 04 Translate and approve content (A, C)

**Goal:** only human-approved, current, consented content gets published.

- [ ] 4.1 `Translator` built as a LangChain runnable (prompt | model | structured parser) producing drafts linked to segment IDs and transcript version; glossary notes for cultural terms.
- [ ] 4.2 `PATCH /v1/recordings/{id}/draft` with expected-version check; return 409 on stale edits.
- [ ] 4.3 `POST /v1/recordings/{id}/review`: reviewer role from server identity only; transcript and translation approved independently.
- [ ] 4.4 Publish only approved, current versions with valid consent; emit an `index_requested` job. Corrections invalidate derived vectors, FTS rows and graph edges.
- [ ] 4.5 Frontend review screen: original, translation and audio side by side.
- [ ] 4.6 Tests: stale edit, forged approval, correction after publish, revoke after publish.

**Gate:** approved segments become searchable; pending, rejected, outdated and revoked content stays excluded.

### 05 Build evidence indexes (B)

**Goal:** make approved text searchable by exact words (Postgres) and by meaning (Pinecone), with permissions enforced inside both.

- [ ] 5.1 `Chunker`: speaker turns or about 100–250 tokens, keeping segment IDs and audio references (pure function, property-tested).
- [ ] 5.2 **Embedding bake-off** on Tamil, English and cross-language queries; record results in `evals/results/`. Pick the model and fix the index dimension.
- [ ] 5.3 `PineconeVectorStore` adapter (via `langchain-pinecone`): namespace per community, metadata schema from the deployment doc, vector ID `recording:segment:version`.
- [ ] 5.4 Postgres full-text index (`tsvector`, `simple` config) with a Tamil tokenization check; replaces `rank-bm25` in `app/retrieval/bm25.py`.
- [ ] 5.5 Permission predicates in **both** searches (Pinecone namespace + filter; SQL `WHERE`). Evidence is hydrated from Postgres and re-checked.
- [ ] 5.6 Index sync worker: upsert on publish, delete on correction or revoke, full rebuild command (`python -m app.worker rebuild-index`). The graph has its own `rebuild-graph` in 7.1.
- [ ] 5.7 Tests: revoke removes results; namespace isolation; stale version not returned.

**Gate:** both indexes return authorized, current evidence with resolvable recording and segment references.

### 06 Retrieve and fuse passages (B)

**Goal:** given a question, return the best 5–8 authorized passages by combining both searches.

- [ ] 6.0 LangSmith ready: projects, hidden inputs and outputs, and the retrieval evaluation dataset (Deployment D7) before measuring anything.
- [ ] 6.1 Query normalizer: keep original wording, add normalized spelling or transliteration variants.
- [ ] 6.2 Retrieve up to 20 candidates per branch, retaining branch rank and provenance.
- [ ] 6.3 Reciprocal rank fusion `k = 60` (extend `app/retrieval/fusion.py`); dedupe by recording, segment, version.
- [ ] 6.4 Select 5–8 passages under a token budget. Optional P1: multilingual reranker.
- [ ] 6.5 Implement `app/agents/hybrid_rag.py` as one small node composing the steps above (no business logic inside the node).
- [ ] 6.6 Evaluate exact-term, paraphrase and cross-language questions; log rank of expected source.

**Gate:** relevant evidence in the shared `Evidence` format; restricted sources never enter model context.

---

## Phase 3 — GraphRAG and agent workflow

**What we're doing:** add relationship reasoning and the full answer pipeline. We build a human-reviewed knowledge graph in Neo4j, retrieve connected evidence from it, then orchestrate everything in LangGraph with verification, one retry and a hard deadline.

### 07 Build the reviewed knowledge graph (B or D)

**Goal:** extract people, places, practices and events from approved text, have humans approve each link, and publish only approved links to Neo4j.

- [ ] 7.1 Postgres migration for `graph_assertion` (source of truth with review state and supporting segment). Neo4j constraints and indexes script (Deployment D4b first). Worker projection `rebuild-graph` that writes **only approved** assertions to Neo4j.
- [ ] 7.2 `GraphExtractor` as a LangChain structured-output chain over permitted text only; output validated by Pydantic (node types and relations from enums).
- [ ] 7.3 Alias resolution within community context; keep ambiguous entities separate; attribute each assertion to its speaker.
- [ ] 7.4 Store review state, temporal context, confidence and policy reference. Only human-approved assertions are queryable; confidence never replaces review.
- [ ] 7.5 Review UI for assertions (approve, reject, edit).
- [ ] 7.6 Fixture: a reviewed two-hop path connecting two recordings.

**Gate:** the two-hop fixture connects recordings through source-backed assertions.

### 08 Retrieve graph evidence (B or D)

**Goal:** answer relationship questions by walking one or two hops in Neo4j, never exposing hidden links.

- [ ] 8.1 `GraphStore` Neo4j adapter (`langchain-neo4j` or the official driver, read-only user, parameterized Cypher only): resolve question entities against reviewed aliases in the user's scope.
- [ ] 8.2 One- or two-hop Cypher from whitelisted query templates; filter nodes and relationships **inside** the pattern (community, review state, policy).
- [ ] 8.3 Re-check each path against Postgres and load supporting approved segments per edge; drop paths with missing, stale or inaccessible evidence.
- [ ] 8.4 Return graph paths plus shared `Evidence` objects; implement `app/agents/graph_rag.py`.
- [ ] 8.5 Tests: relationship queries, hidden edges, graph failure surfaces as an explicit warning.

**Gate:** every returned path has authorized source support and merges with Hybrid RAG without double-counting sources.

### 09 Orchestrate and verify answers (A with B)

**Goal:** run the full question graph: route, retrieve in parallel, merge, verify, answer, with explicit outcomes and a deadline.

- [ ] 9.1 Typed `WorkflowState` with immutable authorization scope, route, evidence, verification results and retry count.
- [ ] 9.2 `supervisor.classify`: LangChain structured output that returns a `Route`; it never produces permissions.
- [ ] 9.3 Run Hybrid and Graph branches in parallel (LangGraph fan-out); keep branch failures as warnings.
- [ ] 9.4 Evidence merger keeps lineage so two hits from one recording count as one source (already scaffolded; extend tests).
- [ ] 9.5 `verifier.verify`: claim support, coverage, translation fidelity, conflicting accounts. At most **one** retrieval retry, then abstain (conditional edge with a retry counter).
- [ ] 9.6 `answer_agent.synthesize`: attributed answer with timestamps and uncertainty; final check of citations, source versions and permissions immediately before delivery.
- [ ] 9.7 Enforce the 45-second request deadline; outcomes `answered | partial | insufficient_evidence` are explicit.
- [ ] 9.8 Postgres checkpointer for LangGraph (`langgraph-checkpoint-postgres`); conversation ownership enforced before enabling persistence.
- [ ] 9.9 `POST /v1/query` wired to the workflow; remove the 503 scaffold guard once `/ready` is green.

**Gate:** answered, partial and insufficient-evidence outcomes are explicit and the workflow stops within the deadline.

### Phase 3 exit — agents complete

**What we're doing:** confirm the agent catalog is fully built.

**Gate:** all eight agents exist as small typed nodes with fake-model tests and an evaluator (A1–A10), and A9 passes with the real adapters swapped in.

---

## Phase 4 — Experience and delivery

**What we're doing:** finish the user journey, prove the whole system meets the MVP checks, and package it so someone else can reproduce the demo. Frontend work on 10 can start earlier using mocks once the 09 query contract is frozen.

### 10 Connect questions and source playback (C with A)

**Goal:** a user asks a question, reads a cited answer and plays the exact audio range.

- [ ] 10.1 Question form with response-language selector; pending, failure and duplicate-submit handling.
- [ ] 10.2 Render answers, citations, partial-result warnings and insufficient-evidence messages.
- [ ] 10.3 `GET /v1/recordings/{id}/media`: access check, then short-lived presigned URL; open cited passage, translation and play the cited time range.
- [ ] 10.4 Handle expired media, revoked sources and stale review versions. Keyboard use, Tamil text wrapping and narrow layouts.

**Gate:** the upload → review → question → citation → playback journey works without manual database inspection.

### 11 Validate the integrated system (A, B, C, D)

**Goal:** measure quality and security against the plan's MVP checks, then fix what fails.

- [ ] 11.1 Freeze corpus version and expected sources for the 12 questions.
- [ ] 11.2 LangSmith evaluators on the frozen dataset: retrieval rank (top 5 in at least 6 of 7 exact and paraphrase cases), graph support (3 of 3), claim grounding, abstention (2 of 2).
- [ ] 11.3 Access tests: cross-community denial, AI-prohibited content, pending reviews, hidden graph edges, revocation, direct media access. **Zero leaks.**
- [ ] 11.4 Timeout and version-change tests; measure median and slowest latency (targets 15 s median, 45 s deadline). Assign owner to every defect, retest fixes.

**Gate:** all MVP checks pass with zero access leaks and no unresolved citation or version defects.

### 12 Package and hand over (A release, B data, C demo, D regression)

**Goal:** a teammate can deploy, run and demo the MVP from the documentation alone.

- [ ] 12.1 Document configuration, migrations, seed data, index rebuild and rollback (`docs/runbooks/`).
- [ ] 12.2 Another contributor deploys and rebuilds approved evidence from the guide alone.
- [ ] 12.3 Regression on the release candidate; rehearse upload, review, lexical and paraphrase queries, graph comparison and playback.
- [ ] 12.4 Team sign-off (A backend and policy, B evidence quality, C experience, D regression), tag the release, hand over API schema, demo inputs, acceptance report and backlog.

**Gate:** a teammate reproduces the demo and recovers the approved collection from the release instructions.

---

## Deployment track

**What we're doing:** stand up AWS and the managed services in three stages, tied to the phases instead of left to the end. Details in the deployment doc, section 8.

### Stage 1 — Thin slice (do after Phase 1 tasks 1.x–3.x work locally)

- [ ] D1 Accounts, MFA, per-environment keys, hooks installed
- [ ] D2 Remote encrypted Terraform state
- [ ] D3 VPC, security groups, KMS, Secrets Manager entries
- [ ] D3b Cognito user pool, groups, app client, first admin invited (before 2.3c)
- [ ] D4 RDS PostgreSQL and migrations (after 1.1)
- [ ] D5 Private S3 audio bucket and presigned URLs (before 3.2)
- [ ] D8 Dockerfile, GitHub Actions OIDC build, scan and push to ECR
- [ ] D9 ECS services (api, ui, worker) with health checks
- [ ] D10 ALB, TLS, DNS, Cognito callback URLs on the final domain (dev token disabled)

### Stage 2 — As features arrive

- [ ] D7 LangSmith projects, hidden inputs and outputs, eval dataset (before 6.0)
- [ ] D6 Pinecone index, namespaces and rebuild (after 5.2)
- [ ] D4b Neo4j AuraDB instance, read and write users, constraints (before 7.1)

### Stage 3 — Release

- [ ] D11 Seed data through the normal upload and review path; smoke test
- [ ] D12 Acceptance run, rollback rehearsal, release tag

---

## P1 and P2 backlog (after P0 passes)

**What we're doing:** parked improvements. Do not start these until every P0 check above passes.

- P1: multilingual reranking, richer review tools, diagnostics, redaction layer for enabling LangSmith content.
- P2: streaming speech, broader language coverage, large graph summaries, production scale, AuraDB Professional or Enterprise sizing for real community data.
