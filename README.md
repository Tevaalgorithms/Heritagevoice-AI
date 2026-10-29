# HeritageVoice AI

Community-controlled oral history preservation with multi-agent AI, Hybrid RAG, GraphRAG, and source-grounded answers.

HeritageVoice AI aims to help communities preserve spoken stories, languages, and cultural knowledge. The intended workflow turns consented recordings into reviewed transcripts and translations, then answers questions with evidence linked to the original sources. Community reviewers retain authority over publication and culturally sensitive material.

## Project status

**Early development scaffold.** The application structure and selected foundational components exist; the complete preservation and question-answering workflows are not implemented yet.

Implemented foundations:

- FastAPI health and readiness endpoints, plus a Streamlit chat shell.
- Typed evidence contracts and a default-deny source access helper.
- LangGraph routing for retrieval, merging, verification, and answer stages.
- Evidence merging that preserves source lineage and graph provenance.
- Reciprocal rank fusion, unit tests, and a locked dependency workflow with CI.

Still to build: trusted user identity, consent and review workflows, audio ingestion, transcription, translation, live retrieval, graph extraction and traversal, semantic verification, answer synthesis, and source playback.

`/health` returns 200 in scaffold mode. `/ready` returns 503. Even with valid development credentials, `/query` returns 503 until the required integrations are implemented. Passing scaffold tests does not establish MVP readiness.

## MVP scope

- A small consented Tamil and English source collection.
- Audio upload and timestamped transcription.
- Human-reviewed transcript corrections, translations, and graph assertions.
- Hybrid retrieval combining lexical and multilingual vector search.
- GraphRAG using reviewed, source-backed paths of at most two hops.
- Verified answers with citations and authorized playback of cited audio ranges.
- Community access controls, consent revocation, and source version checks.

Streaming speech, broad language coverage, large graph summaries, cross-conversation memory, and production scale are deferred. Durable conversation ownership and storage must be implemented before persistent conversations are enabled.

## Architecture

The target system has two connected workflows:

```text
Preservation
Audio + consent → transcription → translation → human review
                → approved evidence indexes and reviewed graph assertions

Question answering
Trusted identity → Supervisor → Hybrid RAG and/or GraphRAG
                 → evidence merger → verification → Answer Agent
                 → final permission and citation checks → response
```

The current LangGraph scaffold captures a trusted `Principal` outside model-written state. Combined retrieval runs sequentially initially. Unconfigured adapters raise `IntegrationNotConfiguredError`; they do not fabricate evidence. Final citation validation and the live agent integrations remain pending.

### Technology baseline

| Component | Current project choice | State |
| --- | --- | --- |
| Backend | Python 3.12 and FastAPI | Scaffold implemented |
| Frontend | Streamlit | Chat shell implemented |
| Orchestration | LangGraph | Workflow topology implemented |
| Lexical retrieval | BM25 adapter with rank-bm25 dependency | Adapter pending |
| Vector retrieval | Pinecone (serverless, one namespace per community) | Managed service; adapter pending |
| Knowledge graph | Neo4j (AuraDB hosted, local container for development) | Adapter pending |
| Durable checkpoints | PostgreSQL | Proposed service; adapter pending |
| Tracing | LangSmith | Full tracing and redaction integration pending |
| Dependencies and checks | uv, pytest, Ruff (complexity limit 5), mypy strict, xenon, GitHub Actions | Configured |

Storage decision: PostgreSQL is the source of truth for records, consent, review state and lexical search. Pinecone and Neo4j hold rebuildable projections of approved content, and every result is re-checked against PostgreSQL before it reaches a prompt. The pgvector option is not used.

## Development segments

Track delivery by completed functionality rather than calendar days. Steps within each segment are ordered; independent work can proceed against agreed contracts and fixtures.

| Segment | Development steps | Completion check |
| --- | --- | --- |
| 01 Application setup | Establish modules, configure services, add health and jobs, connect the interface. | Another contributor can start the web app, API, and worker from the guide. |
| 02 Records and permissions | Define source and consent models, implement trusted identity, freeze contracts, test denied access. | Prohibited operations stop before processing or evidence exposure. |
| 03 Upload and transcription | Validate consented audio, store and queue it, run ASR, display timed drafts. | One real recording produces a reviewable transcript. |
| 04 Translation and approval | Generate aligned drafts, support corrections, record human decisions, gate publication. | Only approved current versions become searchable. |
| 05 Evidence indexes | Select eligible sources, chunk with timestamps, build lexical and vector indexes, synchronize versions. | Both indexes return authorized evidence with source references. |
| 06 Hybrid retrieval | Normalize queries, run filtered searches, fuse ranks, select and evaluate evidence. | Relevant passages are returned without exposing restricted sources. |
| 07 Reviewed graph | Define nodes and relations, extract proposals, resolve aliases, review assertions. | A reviewed two-hop fixture has source-backed relationships. |
| 08 Graph retrieval | Resolve entities, traverse authorized paths, load supporting passages, return shared evidence. | Every path has current authorized support. |
| 09 Agents and verification | Define workflow state, route and merge, verify claims, generate and guard answers. | Answered, partial, and insufficient-evidence outcomes are explicit and bounded. |
| 10 User experience | Connect questions, render outcomes, show evidence, play citations, handle errors. | Upload through cited playback works end to end. |
| 11 Validation | Freeze fixtures, evaluate quality, test isolation and revocation, fix and retest defects. | MVP acceptance gates pass with recorded evidence. |
| 12 Release and handover | Document startup and recovery, reproduce the build, rehearse the demo, record signoff. | A teammate can reproduce the demo and rebuild approved evidence. |

Dependencies: 01–02 establish the foundation; 03–04 produce reviewed sources; 05–06 and 07–08 can progress in parallel; 09 joins retrieval; 10 integrates the experience; 11–12 validate and release it. Frontend work can begin earlier using schema-valid fixtures.

### Team ownership

| Role | Three contributors | Four contributors |
| --- | --- | --- |
| A — Backend and agents | API, ingestion, identity, consent, orchestration, verification, and release. | Same ownership; D adds independent testing. |
| B — Retrieval and data | Source schemas, Hybrid RAG, graph implementation, and evidence evaluation. | Hybrid RAG and shared data; D owns graph implementation. |
| C — Frontend | Upload, review, questions, citations, playback, and user experience. | Same ownership; D adds regression coverage. |
| D — Graph and quality | Responsibilities shared by A, B, and C. | GraphRAG, independent regression, acceptance evidence, and release rehearsal. |

All twelve segments are P0 for the intended MVP. P1 improvements include reranking, richer review tools, and retrieval diagnostics. Resolve permission, citation, and version defects before release.

## Local setup

Prerequisites: uv and Python 3.12. Run from the project directory:

```sh
uv sync --locked
cp .env.example .env
```

Copy the environment example only on first setup; preserve an existing `.env`. Set a strong `HERITAGEVOICE_DEV_API_TOKEN` locally, then start the API:

```sh
uv run uvicorn app.api.main:app --reload --host 127.0.0.1
```

In a second terminal:

```sh
uv run python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1
```

- API documentation: <http://127.0.0.1:8000/docs>
- Interface: <http://127.0.0.1:8501>

The development token is a local access gate, not user authentication. Keep the scaffold local and use synthetic or explicitly approved fixtures until trusted identity and retrieval controls are implemented.

### Optional infrastructure

Compose defines PostgreSQL and Neo4j for local development. Pinecone is a hosted service and has no local container. Set `POSTGRES_PASSWORD` and `NEO4J_PASSWORD` in `.env` before starting them:

```sh
docker compose --profile infrastructure up -d
docker compose --profile infrastructure ps
docker compose --profile infrastructure down
```

These services are not connected to the query endpoint yet. Volumes retain data across restarts; `down -v` deletes that data. Before release, pin tested image versions and verify readiness for every required service.

## API alignment

Current application routes are `GET /health`, `GET /ready`, and `POST /query`. The planned contract is:

| Planned endpoint | Purpose |
| --- | --- |
| `POST /v1/recordings` | Validate and queue a consented upload. |
| `GET /v1/jobs/{id}` | Return processing and review status. |
| `GET /v1/recordings/{id}` | Return authorized metadata and timed segments. |
| `PATCH /v1/recordings/{id}/draft` | Save version-checked corrections. |
| `POST /v1/recordings/{id}/review` | Record trusted human review decisions. |
| `POST /v1/recordings/{id}/revoke` | Revoke consent and deny further access. |
| `POST /v1/query` | Return verified answers, citations, graph paths, and warnings. |
| `GET /v1/recordings/{id}/media` | Authorize cited audio playback. |

These versioned endpoints are planned, not available commands. Extend the evidence contract with recording and segment IDs, timestamp ranges, language, translation versions, consent references, and review status. Add response language and retrieval mode to query requests, and graph paths and warnings to responses.

## Community permissions and provenance

The current policy helper recognizes `public` and `researcher` as OR grants and denies unknown labels. The complete MVP must additionally enforce community membership, operation-specific consent, human approval, revocation, and current source versions.

Apply authorization inside lexical retrieval, vector retrieval, graph traversal, source loading, context construction, and final delivery. Reading a recording does not automatically permit translation, indexing, or AI processing. Validate every graph node, edge, and supporting passage. Preserve attribution and distinguish oral recollections from independently verified facts.

Keep secrets and restricted recordings out of version control, prompts without permission, logs, and trace metadata. Tracing is off by default; nested spans and exception data need allowlisting and redaction before tracing is enabled. Memory caches and checkpoints require scope isolation, policy invalidation, and deletion handling before deployment. Mem0 remains disabled and is not installed.

## Validation and release

Initial acceptance uses twelve labeled questions: four exact-term, three paraphrase, three relationship, and two unsupported. Include at least four Tamil or cross-language answerable cases, plus separate permission and isolation tests.

- [ ] A real recording produces human-approved transcript and translation versions.
- [ ] Expected supporting sources appear in the top five for at least six of seven exact-term and paraphrase cases.
- [ ] All three relationship cases return reviewed source-backed graph paths.
- [ ] Factual claims in answerable cases have supporting citations; unsupported cases abstain.
- [ ] Access, revocation, source-version, and media tests show zero leaks or stale evidence.
- [ ] Timeouts, graph failures, and bounded retrieval retries produce explicit outcomes.
- [ ] Upload, review, questions, evidence inspection, and playback work together.
- [ ] Another contributor verifies clean startup, index rebuild, and rollback.

Record latency on the demo environment; proposed targets are a median query time of at most 15 seconds and a 45-second request deadline. Record source, code, prompt, and model versions with evaluation results.

`evals/README.md` currently describes a larger evaluation suite from an earlier plan. Use the initial acceptance suite above for the segment-based MVP, and retain the larger suite for expanded validation. Build the datasets before claiming these gates pass.

## Contributor checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`pyproject.toml` declares dependencies and `uv.lock` fixes the environment. `requirements.txt` is generated; do not edit it manually. When adding a dependency:

```sh
uv add package-name
uv lock --check
uv sync --locked
uv export --locked --no-header --no-dev --format requirements-txt --output-file requirements.txt
```

Commit the dependency declaration, lockfile, and regenerated export together. CI checks lint, formatting, tests, lock consistency, and the runtime export.

## Project layout

```text
app/api/          API transport and development access
app/agents/       Supervisor, retrieval, merger, verifier, and answer stages
app/graph/        Typed workflow state and LangGraph routing
app/models/       Shared evidence and query contracts
app/retrieval/    Lexical and vector adapters, plus rank fusion
app/security/     Trusted principal and evidence access checks
app/memory/       Development checkpoints and deferred persistence adapters
frontend/         Streamlit interface
ingestion/        Ingestion contract; processing implementation pending
data/             Local sources and generated indexes; content ignored
evals/            Evaluation guidance and future reports
tests/            Scaffold API, workflow, and invariant tests
```

## Secret scanning

Run `scripts/install-hooks.sh` once per clone. The commit hook (`.githooks/pre-commit`) blocks `.env`, Terraform state, plans and
`*.tfvars`, key files, and anything gitleaks detects; CI re-scans the whole history. See [`AGENTS.md`](AGENTS.md).

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
