# HeritageVoice AI — MVP Deployment Resources

Derived from the Team 16 *HeritageVoice AI Development Plan*, the *Project Architecture* document (both kept outside the repository) and the current scaffold.
Task list: [`docs/planning/TODO.md`](../planning/TODO.md).
Stack: **LangGraph + LangChain + LangSmith**, **Pinecone** for vectors, **Neo4j AuraDB** for the graph, **AWS** for hosting.

> Prices, model names and regional availability change. Verify each item against the vendor's pricing page before committing budget.

## Overview: end-to-end resources and flow

### Resources

```text
USER (browser, HTTPS)
        │
   Route 53 + ACM cert              Amazon Cognito (user pool: groups admin / reviewer / member)
        │                                  │ Hosted UI login, MFA, JWT access token
       ALB ── / ──────────> ECS Fargate: UI (Streamlit)
        │                          │
        └─ /v1/* ─> ECS Fargate: API (FastAPI + LangGraph) <──┐
                          │                                    │ jobs
                          │                    ECS Fargate: Worker (ingest, index, graph projection)
                          │                                    │
   ┌──────────────┬───────┴───────┬───────────────┬────────────┴──────┐
   ▼              ▼               ▼               ▼                   ▼
 RDS Postgres   Pinecone       Neo4j AuraDB    S3 (private)     AI providers
 source of      vectors,       reviewed graph  audio, presigned  ASR (Transcribe/
 truth, FTS,    namespace      (derived copy)  URLs only         Whisper), LLM,
 jobs, LangGraph per community                                    embeddings
 checkpoints    (derived copy)

 Side services: Cognito (auth) · Secrets Manager + KMS · CloudWatch · ECR · GitHub Actions (OIDC) · LangSmith (traces, content hidden)
```

### Sign-in (both flows)

```text
Browser ──> Cognito Hosted UI (password + TOTP MFA) ──> access token (JWT, short-lived)
UI sends  Authorization: Bearer <access token>  ──> API
API: verify JWT (signature, issuer, client, expiry) ──> look up user by `sub` in Postgres
     (status, community memberships) ──> build server-side Principal ──> authorize(action, resource)
```

### Flow A: recording to searchable knowledge (preservation)

```text
1. Upload audio ──> API: authenticate, resolve community, validate consent/type/size
                      │ (fails here = no provider call)
2. API ──> S3 (private audio)  +  Postgres: recording + idempotent job (queued)
3. Worker ──> ASR ──> draft transcript, timed segments (Postgres, status=draft)   [NOT searchable]
4. Worker ──> LLM translation draft linked to segments
5. Human reviewer (UI): edits, approves transcript + translation separately
                      │ stale edit = 409, forged approval = rejected
6. Publish (approved + consent valid) ──> index jobs:
      a. chunk (100–250 tokens, keep segment IDs/timestamps)
      b. Postgres full-text rows
      c. embeddings ──> Pinecone (namespace = community, metadata = policy/status)
      d. LLM proposes entities/relations ──> Postgres graph_assertion (pending)
7. Reviewer approves assertions ──> worker projects ONLY approved ones to Neo4j
8. Correction or revoke ──> delete from Pinecone + Neo4j, mark Postgres, old derived data invalid
```

### Flow B: question to verified answer (LangGraph)

```text
User question ──> API: trusted Principal (identity, community, rights) captured outside model state
        │
   [Supervisor]  classify route: hybrid / graph / both / clarify / refuse  (never grants access)
        │
   ┌────┴─────────────────────────────┐
   ▼                                  ▼
[Hybrid RAG]                      [GraphRAG]
 normalize query                   resolve entities vs reviewed aliases
 Postgres FTS  (top 20) ┐          Neo4j Cypher, 1–2 hops, filters inside pattern
 Pinecone      (top 20) ┴─ RRF    read-only user
 k=60, dedupe, pick 5–8            re-check paths + load support segments from Postgres
   │                                  │
   └────────────┬─────────────────────┘
                ▼
        [Evidence Merger]  common format, merge by lineage (same recording = one source)
                ▼
        [Verifier]  claims supported? coverage? conflicts? translations?
                │  insufficient ──> ONE retrieval retry ──> else abstain
                ▼
        [Answer Agent]  attributed answer, timestamps, uncertainty
                ▼
   Final gate: citations valid, source versions current, permissions re-checked
                ▼
   Response: answered | partial | insufficient_evidence  (+ citations, graph paths, warnings, trace ID)
                ▼
   UI: citation click ──> API access check ──> short-lived S3 presigned URL ──> play cited time range
```

### Who owns what

| Data | Source of truth | Derived copy | Rebuild |
| --- | --- | --- | --- |
| Recordings, consent, versions, reviews | Postgres | none | restore RDS snapshot |
| Audio | S3 | none | S3 versioning |
| Vectors | Postgres (approved text) | Pinecone | `rebuild-index` |
| Graph | Postgres `graph_assertion` | Neo4j | `rebuild-graph` |
| Traces | none | LangSmith (content hidden) | n/a |
| Identities, roles, community membership | Cognito (login, groups) + Postgres (membership, status) | none | re-invite users; membership from Postgres backup |

Pinecone and Neo4j never decide access. Namespaces and Cypher filters only narrow results; Postgres plus the server-side principal make the final decision before anything reaches the model.

The sections below go into detail on each part.

## 1. Decisions to confirm first

| # | Decision | Recommendation | Why |
| --- | --- | --- | --- |
| 1 | **Pinecone is a vector database only. It is not a graph database.** | Pinecone for vectors. **Neo4j AuraDB** for the reviewed knowledge graph (Free tier for dev and demo, Professional before real community data). | The plan needs one- and two-hop traversal with filtering during traversal. Neo4j does this natively in Cypher. |
| 2 | Postgres stays the system of record. | Pinecone and Neo4j hold **derived, rebuildable** projections of approved Postgres rows. | The plan requires "index rebuild and rollback" and instant revocation. AuraDB Free has no backups, so rebuild-from-Postgres is also the recovery path. Every hit and every graph path is re-checked against Postgres before it reaches a prompt. |
| 3 | Lexical search | Postgres full-text search (`tsvector`, `simple` config for Tamil). | Plan segment 05. It replaces the in-memory `rank-bm25` in the scaffold. |
| 4 | Hosting | AWS (ECS Fargate, RDS, S3). | Matches the private audio storage, short-lived media URLs and secrets handling the plan needs. |
| 5 | Authentication and roles | **Amazon Cognito**: one user pool, three groups (`member`, `reviewer`, `admin`). Community membership and user status live in Postgres. | Section 3. Cognito proves *who*; application code decides *what* (plan: server-controlled identity). |

**Scaffold changes this implies:** drop `qdrant-client` and the `qdrant` service in `docker-compose.yml`. Keep `neo4j` (and its local service for development). Add `pinecone`, `langchain-pinecone` and `langchain-neo4j`. Update the README technology table. Run `uv lock` and regenerate `requirements.txt` (see `AGENTS.md`).

## 2. Resource inventory

### 2.1 Compute and networking (AWS)

| Resource | MVP sizing | Purpose |
| --- | --- | --- |
| VPC, 2 AZs, private subnets for tasks and DB, public subnets for ALB | 1 NAT gateway (largest fixed cost; see 7) | Isolation. RDS and tasks never public. |
| ECR repositories | 1 image, 3 entry points | Built from the repo. Pin base image digests. |
| ECS Fargate cluster | 3 services: `api` (0.5 vCPU / 1 GB), `ui` (0.5 / 1 GB), `worker` (1 / 2 GB) | Run the apps with `uv`. |
| Application Load Balancer + ACM certificate | 1 ALB, HTTPS only | TLS termination. `/` to UI, `/v1/*` to API. |
| Route 53 (or existing DNS) | 1 hosted zone, 2 records | Demo domain. |

### 2.2 Data

| Resource | MVP sizing | Purpose |
| --- | --- | --- |
| RDS PostgreSQL 16 | `db.t4g.small`, 20 GB gp3, Multi-AZ off for MVP, automated backups on, encrypted | Records, consent, versions, review decisions, FTS index, graph tables, job table, LangGraph checkpoints (`langgraph-checkpoint-postgres`). |
| S3 bucket (audio) | Block Public Access, SSE-KMS, versioning, no public ACLs | Private recordings. Playback only through short-lived presigned URLs issued after an access check. |
| S3 bucket (Terraform state) | Versioned, encrypted, with DynamoDB lock or S3 native locking | Remote encrypted backend, as `AGENTS.md` requires. |
| Neo4j AuraDB | Free for dev and demo; Professional (smallest size) before real data. Same cloud and region as the app. | Reviewed graph projection (section 5). Bolt over TLS (`neo4j+s://`). |
| Pinecone serverless index | 1 index, cosine, AWS region matching the app, dimension = embedding model | See section 4. |

### 2.3 AI services

| Need | Option | Notes |
| --- | --- | --- |
| Orchestration | LangGraph (already in scaffold) | Postgres checkpointer. State carries an immutable authorization scope. |
| LLM calls | LangChain chat model, for example `langchain-anthropic` | Used for translation drafts, entity extraction, verification and answer synthesis. Keep the model name in settings. |
| Embeddings | Pinecone Inference `multilingual-e5-large` (1024 dim) **or** a provider embedding via LangChain | Must be **evaluated on Tamil and cross-language queries** (plan segment 05). Dimension is fixed at index creation, so choose before indexing. |
| Reranking (P1) | Pinecone Inference multilingual reranker | Optional after P0 passes. |
| ASR | Amazon Transcribe (supports Tamil `ta-IN`) **or** a Whisper API | Run a bake-off on the real consented recording. Timestamps must be valid. |
| Tracing and evals | LangSmith (SaaS) | One project per environment. Inputs and outputs hidden until redaction exists. |

### 2.4 Security and operations

| Resource | Purpose |
| --- | --- |
| Amazon Cognito user pool | 1 pool, 3 groups, 1 app client for the UI, self-sign-up off, TOTP MFA required, free tier for small user counts | Authentication and coarse roles. Section 3. |
| AWS Secrets Manager | `PINECONE_API_KEY`, `LANGSMITH_API_KEY`, LLM key, DB password, API token. Injected into ECS task definitions. Nothing in the repo. |
| KMS key | Encrypts S3, RDS and secrets. |
| IAM roles | Task role scoped to one S3 bucket and its own secrets. Separate execution role. CI role via OIDC (no long-lived AWS keys). |
| Security groups | ALB → tasks → RDS only. RDS accepts traffic from task SG only. |
| CloudWatch log groups and alarms | 5xx rate, task restarts, RDS CPU and storage, p95 latency. Log retention 30 days. |
| AWS Budgets | Monthly alert, so a runaway job is caught early. |
| GitHub Actions | Existing lint, test and `secrets` jobs plus build, push and deploy. |

## 3. Identity and RBAC (Amazon Cognito)

### 3.1 Roles

| Role (Cognito group) | Who | Can | Cannot |
| --- | --- | --- | --- |
| `member` (normal user) | Community members, students, researchers | Ask questions, read published and authorized evidence, play authorized audio, upload recordings with a consent reference for their own community | Approve content, see drafts or pending items of others, see other communities, change roles |
| `reviewer` | Trusted human reviewers, per community | Everything a member can, plus edit drafts, approve transcript, translation and graph assertions, mark culturally sensitive material | Manage users, approve their own uploads, bypass consent |
| `admin` | Platform operators | Invite and disable users, assign groups and community membership, revoke recordings, trigger index and graph rebuilds, read audit logs | Read restricted content just by being admin; approve content; bypass community scope or consent |

An LLM never has a role and never grants access. Workers use IAM roles, not Cognito identities.

### 3.2 One pool with groups, not separate pools

Use **one user pool with groups**. Separate pools per role mean separate logins, duplicate configuration and no way for one person to hold two roles. Use separate pools only if admins must have a completely different sign-in policy (for example a different identity provider). Pool-wide TOTP MFA covers reviewers and admins for the MVP.

### 3.3 Where each fact lives

| Fact | Source | Why |
| --- | --- | --- |
| Who the user is (`sub`) | Cognito | Authentication |
| Role | Cognito group (`cognito:groups` claim), intersected with Postgres `app_user.role` | Token alone is not enough |
| Community membership | **Postgres** `community_member (user_id, community_id, role)` | Plan requires server-controlled membership; instant change, no token refresh needed |
| Account active or disabled | Postgres `app_user.status`, plus Cognito disabled flag | A disabled user is denied immediately even with a valid token |
| Consent and rights | Postgres | Plan segment 02 |

Never put community IDs or permissions in custom Cognito attributes that the client can influence.

### 3.4 Request authorization chain

1. UI signs in through the Cognito Hosted UI (authorization code flow with PKCE).
2. API verifies the **access token** on every request: signature (cached JWKS), `iss`, `token_use = access`, `client_id`, `exp`. ID tokens are never accepted by the API.
3. API loads `app_user` by `sub`. Missing or disabled means deny.
4. API builds the `Principal` (user, role, community IDs) on the server and passes it into LangGraph outside model-written state.
5. A pure `authorize(principal, action, resource)` function decides, using a permission table per role. Hidden and missing resources return the same safe response.

Permission table (code, not scattered `if`s):

| Action | member | reviewer | admin |
| --- | --- | --- | --- |
| `recording:upload` | own community | own community | no |
| `query:ask` | yes | yes | yes (still community-scoped) |
| `media:play` | authorized, published | authorized | authorized |
| `draft:edit` | own drafts | assigned community | no |
| `review:approve` | no | assigned community, not own upload | no |
| `recording:revoke` | no | no | yes |
| `user:manage` | no | no | yes |
| `index:rebuild` | no | no | yes |

### 3.5 Pool configuration

| Setting | Value |
| --- | --- |
| Self-sign-up | Off. Admin invites users; first login forces a password change. |
| MFA | Required, TOTP (avoid SMS cost and SIM risk) |
| Password policy | 12+ characters |
| App client | Authorization code + PKCE, exact callback URLs, no implicit flow |
| Token lifetime | Access 15–60 min, refresh 1 day or less |
| Groups | `member`, `reviewer`, `admin`; changed only by an admin or Terraform |
| Revoking a user | Disable in Cognito, set `app_user.status = disabled`, call global sign-out. The Postgres check blocks immediately. |
| Audit | Log every role change, approval and revoke with user ID and trace ID, but no transcript content |
| Terraform | Pool, groups and client defined in `infra/`; users are not |

**Streamlit note:** verify early in Phase 1 how the UI obtains and stores the access token. `st.login` exposes user information but may not expose the access token the API needs, so a small server-side OIDC flow (for example with `authlib`) may be required. Tokens stay in server-side session state, never in URLs or logs.

### 3.6 Tests that must exist

- Expired, wrong-issuer, wrong-client and ID-token requests are rejected.
- A valid token for a disabled user is rejected.
- Member calling reviewer and admin endpoints gets 403 (or the safe not-found response).
- Reviewer cannot approve their own upload.
- Admin cannot read restricted content outside their community or without consent.
- Changing community membership in Postgres takes effect on the next request.

## 4. Pinecone design (vectors)

| Item | Design |
| --- | --- |
| Index | One serverless index `heritagevoice-<env>`. Cosine. Dimension from the chosen embedding model. |
| Namespace | **One per community**, for example `community-<id>`. A query always names exactly one namespace taken from the server-side principal, never from client input. |
| Vector ID | `<recording_id>:<segment_id>:<transcript_version>` so a corrected version never overwrites silently. |
| Metadata | `recording_id`, `segment_id`, `transcript_version`, `language`, `start_s`, `end_s`, `policy_ref`, `ai_processing_allowed`, `status`. Store **no transcript text** if you can avoid it; hydrate text from Postgres. |
| Query filter | `{"status": "published", "ai_processing_allowed": true}` applied in the Pinecone query (filter-before-return), then re-validated against Postgres. |
| Revocation and corrections | Delete vectors by ID or by metadata filter in the namespace, mark the Postgres row revoked, and rely on the Postgres re-check for the eventual-consistency window. |
| Rebuild | A worker command re-embeds approved Postgres rows into a fresh index. Swap by config. This is the rollback path. |
| Environments | Separate indexes for dev, staging and demo. Never share. |

**Limits to design around:** Pinecone does not support joins or graph traversal, and metadata filters only narrow candidates. They are not your authorization boundary; Postgres is.

## 5. Graph design (Neo4j AuraDB)

**Source of truth:** Postgres table `graph_assertion` (subject, relation, object, `asserted_by`, `review_state`, confidence, validity dates, `policy_ref`, supporting `segment_id` + `transcript_version`). A worker **projects only approved assertions** into Neo4j. Un-approving, correcting or revoking removes the relationship.

| Neo4j element | Design |
| --- | --- |
| Node labels | `Recording`, `Segment`, `Speaker`, `Place`, `Event`, `Practice`, `Theme`. Each has `id` (unique constraint) and `community_id`. |
| Relationship types | Fixed set: `SPOKE_IN`, `MENTIONS`, `DESCRIBES`, `OCCURRED_AT`, `RELATED_TO`, `SUPPORTED_BY`. |
| Relationship properties | `assertion_id`, `asserted_by`, `review_state`, `confidence`, `valid_from`, `valid_to`, `policy_ref`, `ai_processing_allowed`, `community_id`. |
| Indexes | Unique constraints on node `id`; index on `community_id` and on alias lookup. |
| Query rules | Parameterized Cypher only. Traversal depth ≤ 2. Filters on `community_id`, `review_state = 'approved'` and policy sit **in the pattern predicate**, so hidden edges are never walked. Relationship types come from a code whitelist (they cannot be parameters). |
| Support check | For each returned path, load the supporting segments from Postgres and drop any path with missing, stale or inaccessible support. |
| Database users | App uses a **read-only** user for queries; the worker uses a separate write user. |
| Rebuild | `rebuild-graph` command wipes and reprojects approved assertions from Postgres. This is also disaster recovery on AuraDB Free (no backups). |

Wrap it all in a `GraphStore` interface, so the agents never import `neo4j` directly.

**AuraDB Free caveats:** about 200k nodes and 400k relationships; pauses after roughly 3 days of inactivity (resume before demos) and can be deleted if left paused; no backups; no SLA. Treat it as dev and demo only.

## 6. Environment variables (names only, values live in Secrets Manager)

Add these to `.env.example` with **empty values**:

```text
PINECONE_API_KEY=
PINECONE_INDEX=
HERITAGEVOICE_DATABASE_URL=
HERITAGEVOICE_AUDIO_BUCKET=
HERITAGEVOICE_LLM_API_KEY=
COGNITO_REGION=
COGNITO_USER_POOL_ID=
COGNITO_APP_CLIENT_ID=
NEO4J_URI=
NEO4J_READ_USER=
NEO4J_READ_PASSWORD=
NEO4J_WRITE_USER=
NEO4J_WRITE_PASSWORD=
LANGSMITH_TRACING=false
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=heritagevoice-ai-<env>
```

## 7. Rough monthly cost (demo scale, order of magnitude only)

| Item | Approx. |
| --- | --- |
| Fargate (3 small services, always on) | $50–90 |
| RDS `db.t4g.small` + storage | $30–45 |
| ALB | $20–25 |
| NAT gateway | $35+ (cheaper: VPC endpoints, or public subnets with strict security groups for the demo) |
| Pinecone serverless (tiny corpus) | free tier to ~$10 |
| Neo4j AuraDB | Free for demo; about $65 for Professional later |
| S3, CloudWatch, Secrets Manager | $5–15 |
| Amazon Cognito | free tier covers a small user base (TOTP MFA has no SMS cost); verify current tier pricing |
| LLM, embeddings, ASR usage | usage based; the 6 recordings and 12 questions are small |
| LangSmith | free developer tier is enough to start |
| **Total** | **roughly $150–250 / month** (add about $65 once on AuraDB Professional), mostly fixed infrastructure |

**Cheapest alternative for a short demo:** one `t4g.medium` EC2 running `docker compose` (API, UI, worker, Postgres) plus S3 and Pinecone. About $40/month, but no managed backups or HA. Acceptable for a rehearsal, not for community data.

## 8. Step-by-step deployment

Each step has a **done check**. Do not continue until it passes.

Steps are done in three stages that match [`TODO.md`](../planning/TODO.md) (Deployment track):

| Stage | Steps | When |
| --- | --- | --- |
| 1. Thin slice | 1–6, 10–12 | After Phase 1 works locally: accounts, network, database, Cognito, audio storage, images, ECS, ALB and TLS |
| 2. As features arrive | 9 (LangSmith), 7 (Pinecone), 8 (Neo4j) | LangSmith before Phase 2 measurement (task 6.0), Pinecone after the embedding choice (5.2), Neo4j before the graph build (7.1) |
| 3. Release | 13–14 | Seed data, acceptance, rollback rehearsal |

Until a service exists, `/ready` skips it (see `TODO.md` task 1.4).

### Step 1 — Accounts and access
1. Create or confirm: AWS account (enable MFA, create a non-root admin), Pinecone project, LangSmith workspace, LLM provider account, GitHub repo.
2. Create **separate** API keys per environment. Store them in a password manager first.
3. Run `scripts/install-hooks.sh` and install gitleaks on every machine.

*Done when:* nobody uses root credentials and no key is in the repo or `.env.example`.

### Step 2 — Remote Terraform state
1. Create the encrypted, versioned S3 bucket and lock mechanism by hand (one-time bootstrap).
2. Add the `backend "s3"` block in `infra/`.
3. Confirm `*.tfstate*`, `*.tfvars`, `.terraform/` are git-ignored. Never paste `plan` output anywhere.

*Done when:* `terraform init` works from a second laptop.

### Step 3 — Network and security baseline
1. Terraform: VPC, subnets, route tables, NAT or endpoints, security groups, KMS key.
2. Create the Secrets Manager entries (names only in code, values entered in the console).

*Done when:* a test task in a private subnet can read one secret and reach the internet.

### Step 4 — Database
1. Terraform: RDS PostgreSQL 16 in private subnets, encrypted, backups on.
2. Run migrations from a one-off ECS task (`uv run alembic upgrade head` or the project's migration command).
3. Create roles: `app_rw` for API and worker, `migrator` for migrations.

*Done when:* the API `/ready` check reaches Postgres and migrations are repeatable on an empty database.

### Step 5 — Identity (Cognito)
1. Terraform: user pool (self-sign-up off, TOTP MFA required, password policy), groups `member`, `reviewer`, `admin`, one app client with PKCE and exact callback URLs, Hosted UI domain.
2. Store `COGNITO_USER_POOL_ID` and `COGNITO_APP_CLIENT_ID` as configuration (they are not secrets; any client secret goes in Secrets Manager).
3. Run migrations for `app_user` and `community_member`. Invite the first admin through the console, then invite everyone else through the app.
4. Run the section 3.6 tests against the dev pool.

*Done when:* a member, a reviewer and an admin can each sign in with MFA, and each gets only the actions in the permission table.

### Step 6 — Audio storage
1. Terraform: private S3 bucket, Block Public Access, SSE-KMS, lifecycle for incomplete uploads.
2. Task role gets `s3:GetObject` / `PutObject` on this bucket only.
3. Implement presigned URL issuance behind the access check (`TODO.md` task 10.3; the upload side is task 3.2).

*Done when:* a direct anonymous GET on an object returns 403 and a presigned URL expires on time.

### Step 7 — Pinecone
1. Create the serverless index in the same cloud and region as the app, with the dimension of the chosen embedding model.
2. Run the Tamil and English embedding bake-off **before** loading data (`TODO.md` task 5.2).
3. Add `PINECONE_API_KEY` to Secrets Manager and `PINECONE_INDEX` to the task definition.
4. Run the rebuild command against the dev index and confirm namespaces per community.

*Done when:* a query in namespace A never returns a vector from namespace B, and a deleted vector stops being returned after the Postgres re-check.

### Step 8 — Neo4j AuraDB
1. Create an AuraDB Free instance (Professional before real data) in the same cloud and region as the app. Save the generated password immediately; it is shown once.
2. Put the URI and credentials in Secrets Manager. Create separate read-only and write users.
3. Create the uniqueness constraints and indexes from section 5 through a migration script.
4. Run `rebuild-graph` against the two-hop fixture.

*Done when:* the read-only user cannot write, a query as community A never returns community B edges, and a revoked assertion disappears after the next projection.

### Step 9 — LangSmith
1. Create projects `heritagevoice-ai-dev`, `-staging`, `-demo`.
2. Keep `LANGSMITH_TRACING=false` by default. For staging, set `true` with `HIDE_INPUTS` and `HIDE_OUTPUTS` still `true` until redaction exists.
3. Upload the 12 evaluation questions as a LangSmith dataset (IDs and expected source IDs only, no restricted text).

*Done when:* one traced run shows node timings and trace ID, but no question text or transcript content.

### Step 10 — Container images and CI/CD
1. Add a `Dockerfile` (multi-stage, `uv sync --frozen`, non-root user). One image, three commands: `api`, `ui`, `worker`.
2. GitHub Actions: lint, tests, gitleaks, then build, scan, push to ECR on `main`. Authenticate to AWS with OIDC.
3. Tag images with the git SHA. Never deploy `latest`.

*Done when:* a merge to `main` produces a scanned image in ECR.

### Step 11 — ECS services
1. Terraform: task definitions, services, log groups, autoscaling off for MVP.
2. Inject secrets by reference, never as plain environment values.
3. Health checks: API `/health` for liveness, `/ready` for the ALB target group.

*Done when:* all three services are stable for 30 minutes with no restarts.

### Step 12 — Load balancer, TLS and DNS
1. Terraform: ALB, ACM certificate, HTTPS listener, HTTP-to-HTTPS redirect, path rules.
2. Point the demo domain at the ALB.
3. Confirm the Cognito callback and logout URLs use the final HTTPS domain. The dev API token must not be enabled in the demo environment.

*Done when:* the UI loads over HTTPS and `/v1/query` rejects unauthenticated calls.

### Step 13 — Seed data and smoke test
1. Load the six approved recordings or fixtures through the normal upload and review path, not by direct DB inserts.
2. Run the index rebuilds (Postgres → Pinecone, Postgres → Neo4j).
3. Run the smoke test: upload → transcript → review → publish → ask → citation → playback.

*Done when:* the user journey works without manual database inspection.

### Step 14 — Acceptance, rollback rehearsal and handover
1. Run the evaluation suite (`evals/`) and the access tests: cross-community, revoked, AI-prohibited, pending, direct media.
2. Record median and slowest query time. Targets: median ≤ 15 s, deadline 45 s.
3. Rehearse rollback: redeploy the previous image tag, restore the RDS snapshot, rebuild the Pinecone index and the Neo4j graph.
4. Ask another contributor to deploy from the guide alone. Tag the release.

*Done when:* all MVP release checks in the plan pass with zero access leaks.

## 9. Code standards for everything deployed

| Rule | Enforcement |
| --- | --- |
| Cyclomatic complexity ≤ 5 per function (radon grade A) | Ruff `C901` with `max-complexity = 5`, plus `xenon --max-absolute A --max-modules A --max-average A` in CI |
| Short functions: ≤ 20 statements, ≤ 5 branches, ≤ 4 arguments, ≤ 3 returns | Ruff `PLR0912`, `PLR0913`, `PLR0915`, `PLR0911` |
| Guard clauses and early returns instead of nested `if` | Code review |
| Dispatch tables (`dict[Enum, Callable]`) instead of `if/elif` chains | Code review |
| Ports and adapters: `VectorStore`, `GraphStore`, `Transcriber`, `LLM` protocols; agents depend on protocols only | Keeps vendors replaceable and unit tests free of network calls |
| Role checks as a table (`dict[Action, set[Role]]`), never scattered `if role ==` | Keeps `authorize` at complexity 1–2 and easy to audit |
| Pure functions for ranking, fusion, filtering and permission decisions | Easy to test exhaustively |
| Typed everywhere, Pydantic models at boundaries | `ruff` + optional `mypy --strict` on `app/` |
| LangGraph nodes: one responsibility, no nested closures, state in/out only | Each node is a module-level function; the graph file only wires them |

## 10. Risks specific to this stack

| Risk | Mitigation |
| --- | --- |
| Trusting token claims for community access | Membership read from Postgres on each request; access tokens short-lived |
| Admin role used as a backdoor to content | Admin has no content permissions; consent and community scope always apply |
| Treating Pinecone filters as authorization | Namespace from the server principal, plus Postgres re-check before prompt construction |
| Pinecone eventual consistency after revoke | Postgres re-check; test it explicitly |
| Embedding model weak on Tamil | Bake-off first; record Tamil results separately (plan requirement) |
| Transcript text in traces | Hidden inputs and outputs; add a redaction layer before enabling content |
| AuraDB Free pauses, has no backups and no SLA | Resume before demos; rebuild from Postgres; move to Professional for real data |
| Neo4j projection drifts from Postgres review state | Re-check every path against Postgres; test revoke and un-approve |
| Fixed monthly cost for a small demo | Tear down staging between sprints; Budgets alarm |
