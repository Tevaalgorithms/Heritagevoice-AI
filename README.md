# HeritageVoice AI

![HeritageVoice AI — oral storytelling connected to preserved cultural knowledge](assets/heritagevoice-banner.png)

> **Our goal:** preserve the voices of today so future generations can hear, learn from and
> understand the wisdom of the past, with communities, not AI, in control of their own heritage.

**A community-controlled platform that turns consented oral histories into reviewed, searchable
knowledge, and answers questions with citations that lead back to the original voice.**

Record songs, stories, lessons and practices in your own language. Keep them with the consent of the
people who shared them. Let anyone ask questions and hear the exact moment an answer came from.

**Live site: [heritagevoice.org](https://heritagevoice.org)**. Browse and listen to what communities
have shared openly, with no account. Sign in to ask questions and add recordings.

## Why this project exists

Every language carries generations of stories, traditions and knowledge. Many are disappearing as
fewer people speak them and younger generations lose the chance to learn them. When a language
goes, we lose more than words: we lose practices, history and ways of understanding the world.

Existing digital resources focus on widely spoken languages. Smaller communities are left with
few tools to document their heritage, and general-purpose AI tools make two things worse:

- **They guess.** A chatbot happily invents a "traditional remedy" or a "village history" that no
  elder ever told. For heritage knowledge, an invented answer is worse than no answer.
- **They ignore ownership.** Communities need to decide who may hear a recording, and to change
  their mind later.

HeritageVoice AI is built around the opposite rules:

| Principle | What it means in practice |
| --- | --- |
| **Consent first** | Nothing is processed or shared until the speaker's consent is recorded. Consent can be withdrawn and takes effect at once. |
| **Humans decide** | AI drafts transcripts, translations and relationships. People review them. Only approved material is searchable. |
| **Grounded answers** | Answers use the recordings only. Every claim is checked against its sources and carries a citation. If the recordings do not say, the answer says so. |
| **Default-deny access** | The server decides who may see what. Nothing a client or a model says can widen it. |
| **Community-controlled** | Families and groups, coordinators and open sharing, chosen by the people who own the knowledge. |

The goal is not to replace native speakers or cultural experts. It is to give communities better
tools to preserve and share their own heritage.

## What it does

- **Contribute.** Record in the browser or upload audio or MP4 in 17 languages. Share with a family
  or group, or openly with everyone; either way the speaker's consent is recorded first. Optionally
  credit the speaker and say where the knowledge came from (a family elder, a book, a website).
- **Review.** Speech is transcribed and translated, then people check it. Only approved, current
  versions are searchable.
- **Find.** Anyone can search the openly shared recordings without an account. Signed-in people also
  search what their groups share.
- **Ask.** Questions are answered from the recordings only, using keyword and meaning-based search
  plus a reviewed knowledge graph for "how are these connected" questions. Answers carry
  citations, and you can listen to the cited moment.
- **Follow connections.** The Connections page shows how people, places, songs and customs are
  linked, each with the words in the recording that say it. Search by typing or by voice, in the
  speaker's language or in English, and switch any connection to English. Only relationships a
  person approved are shown.
- **Correct by voice.** An administrator can say how a proposed relationship should read; a model
  suggests the wording, and the administrator checks and approves it.
- **Stay in control.** Groups and coordinators, consent that can be withdrawn at once, "report this
  item", an audit trail, and remedies that always carry a "not medically validated" notice.
- **Administer.** Approve people and manage accounts and roles, choose the language models for each
  job (with fall-backs), see model usage and cost, keep API keys in AWS Parameter Store (never shown
  again), and review proposed relationships.

## Architecture

The system has two flows that meet in the data stores: **preservation** (turning a recording into
approved knowledge) and **question answering** (turning a question into a cited answer).

```mermaid
flowchart TB
    subgraph PRESERVE["1. Preservation: recording to approved knowledge"]
        direction LR
        U["Contributor<br/>record or upload"] --> C{"Consent<br/>recorded?"}
        C -- no --> X["Refused"]
        C -- yes --> S3[("Private audio<br/>S3")]
        S3 --> ASR["Amazon Transcribe<br/>timed transcript"]
        ASR --> TR["Translator agent<br/>draft translation"]
        TR --> REV{"Human review<br/>transcript and translation"}
        REV -- approved --> PUB["Publish current version"]
        PUB --> IDX["Index: keyword and vectors"]
        PUB --> EXT["Graph extractor agent<br/>proposes relationships"]
        EXT --> GREV{"Human review<br/>relationships"}
    end

    subgraph STORES["Stores: PostgreSQL is the source of truth"]
        direction LR
        PG[("PostgreSQL<br/>records, consent, review,<br/>keyword search")]
        PC[("Pinecone<br/>meaning search<br/>rebuildable copy")]
        N4[("Neo4j<br/>reviewed graph<br/>rebuildable copy")]
    end

    IDX --> PG
    IDX --> PC
    GREV -- approved --> PG
    GREV -- approved --> N4

    subgraph ASK["2. Question answering: question to cited answer"]
        direction LR
        Q["Question<br/>+ trusted identity"] --> RW["Rewriter agent"]
        RW --> SUP{"Supervisor agent<br/>choose route"}
        SUP -- text --> HY["Hybrid RAG agent"]
        SUP -- relationships --> GR["Graph RAG agent"]
        SUP -- both --> HY
        HY --> MG["Evidence merger"]
        GR --> MG
        MG --> VF["Verifier agent<br/>check claims"]
        VF -- "not enough, one retry" --> HY
        VF --> AN["Answer agent<br/>write from verified claims"]
        AN --> GATE{"Final permission<br/>and version check"}
        GATE --> OUT["Cited answer<br/>+ audio playback"]
    end

    PG -.-> HY
    PC -.-> HY
    N4 -.-> GR
    PG -.-> GR
    PG -.-> GATE
```

How to read it:

1. **A recording enters only with consent.** Audio is stored privately and transcribed with
   timestamps. A translation is drafted from the transcript.
2. **People approve before anything is searchable.** Drafts stay invisible to search until a
   reviewer approves them. A correction creates a new version and invalidates what was derived
   from the old one.
3. **Approved content is copied into search indexes.** PostgreSQL holds the truth and keyword
   search. Pinecone and Neo4j hold *rebuildable copies*: if either is lost or wrong, it is rebuilt
   from PostgreSQL.
4. **A question runs through a fixed pipeline of agents** (see below). Each retrieval result is
   re-checked against PostgreSQL, and a last permission and version check runs just before the
   answer is returned.
5. **The answer links back to the voice.** Citations point at the exact recording and time range,
   and an authorized reader can play that moment.

### Technology

| Part | Technology |
| --- | --- |
| API, worker | Python 3.12, FastAPI, background jobs in PostgreSQL |
| Interface | Streamlit |
| Orchestration, agents | LangGraph, LangChain (Anthropic and OpenAI models, with fall-backs) |
| Records, keyword search | PostgreSQL 16 (full-text search), Alembic migrations |
| Meaning-based search | Pinecone |
| Knowledge graph | Neo4j |
| Sign-in, speech | Amazon Cognito, Amazon Transcribe |
| Hosting | One small AWS instance, Terraform, GitHub Actions (OIDC, no stored AWS keys) |

## Agents

Each agent has one job, a typed input and output, and no power to grant access. Models are chosen
per job in the admin portal, with fall-backs, so a provider outage degrades one step instead of
the whole product. A step that cannot run records a warning and the pipeline carries on safely.

| Agent | Flow | Task | If it fails |
| --- | --- | --- | --- |
| **Translator** | Preservation | Drafts a translation of each transcript segment. Keeps cultural terms (names, places, kinship words, songs) and treats the transcript as data, never as instructions. | Review continues without a translation draft. |
| **Graph extractor** | Preservation | Reads an approved transcript and *proposes* relationships (person, place, event, practice, theme). Every proposal is checked for a real segment and a known relation, then stored as pending. | Nothing is proposed; nothing reaches the graph. |
| **Correction interpreter** | Preservation | Understands a reviewer's spoken correction of a proposed relationship. The reviewer sees the words it heard and what it wrote, can change either, and approves it themselves. | The reviewer types the change instead. |
| **Question rewriter** | Question | Turns a follow-up ("and her mother?") into a standalone question using the last few turns. Memory is stateless and never widens access. | The original question is used. |
| **Supervisor** | Question | Chooses the route: text search, graph search, both, ask for clarification, or refuse. It routes; it never grants access. | Falls back to text search with a warning. |
| **Hybrid RAG** | Question | Finds passages with keyword and meaning-based search, fuses the ranks and keeps the best five to eight. | Keyword results only, with a warning. |
| **Graph RAG** | Question | Finds relationship paths in the reviewed graph and loads the passages that support each edge. | The question is answered from text, with a warning. |
| **Evidence merger** | Question | Combines both branches, removing duplicates while keeping how each passage was found. | Not model-backed; errors surface. |
| **Verifier** | Question | Proposes the claims the passages actually support, each tied to the passages that say it. Claims citing a passage that was not shown are discarded. May ask for one more retrieval round. | Nothing is claimed: an unverified answer is never produced. |
| **Answer writer** | Question | Writes prose from verified claims only, in the reader's chosen language. Citations, remedy notices and disagreements between sources are added by code, so a model cannot leave them out. | The verified claims are shown as they are. |

Transcription is not an agent: Amazon Transcribe produces the timed transcript, and the
transcript is validated (non-empty, ordered, unique segment IDs) before it is saved.

The question agents run as a [LangGraph](https://langchain-ai.github.io/langgraph/) workflow with
typed state. The reader's identity is captured once on the server and cannot be changed by any
node; every retrieval result is checked against it, and the whole run has a deadline and at most
one retrieval retry.

## Retrieval: RAG and GraphRAG

### Why retrieval at all

A language model on its own does not know your community's recordings, and what it does know it
may state with confidence and get wrong. **Retrieval-Augmented Generation (RAG)** fixes this by
searching the approved recordings first and letting the model answer *only* from what was found.
That gives the three things heritage preservation needs: answers that come from the community's
own words, citations a person can follow, and the ability to say "the recordings do not say".

### Hybrid RAG: finding the right passages

Oral-history questions are a mix of exact names and loosely worded ideas, in several languages,
so no single search is enough.

| Search | Good at | Weak at |
| --- | --- | --- |
| **Keyword** (PostgreSQL full-text) | Exact names, places, rare words, transliterated terms | Paraphrase and other wording |
| **Meaning-based** (Pinecone, multilingual embeddings) | Paraphrase, "same idea, different words", cross-language questions | Exact rare terms |

How we use them:

1. The original question is kept, and a normalized spelling is added without losing the source
   wording.
2. Each search returns up to 20 candidates. **The reader's permissions are applied inside both
   searches**, so restricted passages are never candidates.
3. Ranks are fused with reciprocal rank fusion (k=60) and duplicates are removed by recording,
   segment and version.
4. The best five to eight passages fit the context budget and move on.

If the vector search is down, keyword results are used and a warning is attached.

### GraphRAG: following connections

Some questions are about relationships, not passages: *"Who else mentions the harvest festival?"*,
*"How are these two families connected?"*, *"Which places appear in both stories?"* The answer is
spread across several recordings, so passage search alone misses it. A **knowledge graph** stores
who and what appear and how they relate, so one or two hops can join recordings that never mention
each other directly.

A graph built by a model alone would reintroduce guessing, so ours is *reviewed*:

1. After a transcript is approved, the **graph extractor** proposes relationships, each tied to the
   segment that says it.
2. A person approves or rejects each one on the Relationships page. Confidence never replaces
   review.
3. Approved relationships are written to Neo4j. PostgreSQL stays the source of truth.
4. At question time, **Graph RAG** asks Neo4j only for *candidate paths*. Every edge is then
   re-checked in PostgreSQL: still approved, about the transcript that is approved now, and the
   supporting passage still readable by this person. **A path with any failing edge is dropped
   whole**, so the graph can never reveal more than the text could.
5. What survives returns as ordinary evidence plus the path that led to it, and is merged with the
   Hybrid RAG results.

### When each is used

| Question | Route | Example |
| --- | --- | --- |
| Find a fact, name or story | Hybrid RAG | "What song is sung at the rice harvest?" |
| Relationships across recordings | Graph RAG, usually with Hybrid RAG | "How are these two families connected?" |
| Too vague | Ask to clarify | "Tell me about it." |
| Not allowed | Refuse | A request outside the recordings' purpose |

If Neo4j is not configured, relationship questions fall back to text search with a warning, so the
product works with PostgreSQL alone.

## Quick start (local)

Prerequisites: [uv](https://docs.astral.sh/uv/), Python 3.12 and Docker (for PostgreSQL).

```sh
uv sync --locked
cp .env.example .env                  # then set a strong HERITAGEVOICE_DEV_API_TOKEN and the database URL
docker compose --profile infrastructure up -d postgres
uv run alembic upgrade head
uv run uvicorn app.api.main:app --reload --host 127.0.0.1      # API    http://127.0.0.1:8000/docs
uv run python -m app.worker                                      # background jobs (new terminal)
uv run python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1   # UI http://127.0.0.1:8501
```

The development token is a local access gate, not user authentication. Full walkthrough:
[`docs/runbooks/setup.md`](docs/runbooks/setup.md). New to the code? Read the
[code guide](docs/code-guide.md). `uv run python -m app.skeleton` runs one fixture end to end with
in-memory fakes and prints a cited answer.

## Documentation

| Topic | Where |
| --- | --- |
| Run it locally | [`docs/runbooks/setup.md`](docs/runbooks/setup.md) |
| Deploy to AWS and approval gates | [`docs/runbooks/deploy-single-instance.md`](docs/runbooks/deploy-single-instance.md) |
| Moving the site to a new domain | [`docs/runbooks/change-domain.md`](docs/runbooks/change-domain.md) |
| Repository settings for maintainers | [`docs/runbooks/repository-settings.md`](docs/runbooks/repository-settings.md) |
| Accounts, roles, groups and consent | [`docs/runbooks/accounts.md`](docs/runbooks/accounts.md), [`sharing.md`](docs/runbooks/sharing.md) |
| Models, keys and services | [`docs/runbooks/models.md`](docs/runbooks/models.md), [`integrations.md`](docs/runbooks/integrations.md), [`secrets.md`](docs/runbooks/secrets.md) |
| Search and answering | [`docs/runbooks/retrieval.md`](docs/runbooks/retrieval.md), [`answering.md`](docs/runbooks/answering.md) |
| Languages | [`docs/runbooks/languages.md`](docs/runbooks/languages.md) |
| Connections: search, English and voice | [`docs/runbooks/connections.md`](docs/runbooks/connections.md) |
| Correcting relationships by voice | [`docs/runbooks/voice-correction.md`](docs/runbooks/voice-correction.md) |
| Sign-in domain (Cognito) | [`docs/runbooks/login-domain.md`](docs/runbooks/login-domain.md) |
| Access tests (the denied cases) | [`docs/runbooks/access-tests.md`](docs/runbooks/access-tests.md) |
| **Data stores**: PostgreSQL tables, the vector index, the graph | [`docs/schema/`](docs/schema/README.md) |
| **Why it is built this way** (decision records) | [`docs/adr/`](docs/adr/README.md) |

## Quality standards

Every change must pass these checks (also run by CI):

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run xenon --max-absolute A --max-modules A --max-average A app ingestion frontend
uv run pytest
```

- Cyclomatic complexity of at most 5 per function, at most 4 arguments, strict typing.
- Every access rule has a test for the denied case. Authorization comes only from the server-side
  principal, never from model output or request data.
- Dependencies are locked: change `pyproject.toml`, run `uv lock`, and regenerate
  `requirements.txt` (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- Secrets and restricted recordings never enter Git; a commit hook, CI and tests enforce it.

## Project layout

```text
app/api/          HTTP endpoints
app/agents/       Translator, graph extractor, question rewrite, supervisor, retrieval, graph search, verifier, answer
app/graph/        LangGraph workflows and typed state
app/adapters/     Pinecone, Neo4j, Cognito, Transcribe, S3 and model providers
app/db/           Tables and repositories
app/models/       Shared contracts
app/retrieval/    Keyword and vector search, fusion, eligibility checks
app/security/     Principal, roles and permissions
frontend/         Streamlit interface and legal pages
migrations/       Alembic migrations
infra/            Terraform (Cognito, single-instance hosting, CI roles)
deploy/           Container stack and deploy scripts
evals/            Retrieval evaluation harness and synthetic fixtures
ingestion/        Helpers for text sources (see its README)
tests/            Unit, access and end-to-end tests
scripts/          Git hook installer and Pinecone index setup
docs/             Runbooks, schema of the three data stores, decision records, code guide
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately, as described in
[SECURITY.md](SECURITY.md). Every pull request needs a maintainer's approval before it is merged,
and nothing is deployed without a maintainer approving the deployment.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
