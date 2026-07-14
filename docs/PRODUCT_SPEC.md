# ResumeGraph product specification

## 1. Product statement

ResumeGraph is a controlled AI portfolio assistant that a recruiter or interviewer can open from a resume link or QR code before an interview.

It answers questions about the candidate's published resume, projects, technical decisions, responsibilities, problems encountered, and lessons learned. Answers must be grounded in candidate-provided material and include source citations.

It is not the candidate, does not conduct the interview on the candidate's behalf, and does not answer unrelated general questions.

## 2. Primary users

### Recruiter or interviewer

Needs to:

- enter through a valid, revocable access grant;
- view a concise public candidate/project overview;
- ask questions about authorized projects;
- see cited evidence and clear insufficient-evidence responses;
- use the site without receiving administrative capabilities.

### Administrator

The candidate is the initial sole administrator.

Needs to:

- authenticate separately from recruiter access;
- create and edit project facts;
- upload or paste project knowledge documents;
- inspect ingestion progress and generated chunks;
- publish, unpublish, replace, or delete knowledge;
- create, scope, expire, quota, and revoke recruiter access grants;
- review question history, retrieval evidence, failures, and feedback without exposing secrets.

## 3. Core recruiter flow

1. Recruiter opens an invite link or enters an access code.
2. Backend verifies token digest, expiry, revocation, and quota.
3. Backend exchanges the grant for a short-lived server-side session.
4. Recruiter sees only projects allowed by that grant.
5. Recruiter asks a question.
6. Backend authorizes the request before agent execution.
7. Agent classifies the question and uses only approved read-only tools.
8. Retrieval searches only published chunks inside the allowed project scope.
9. Agent either:
   - answers with validated citations;
   - answers only the supported portion;
   - asks for narrow clarification; or
   - refuses because the question is out of scope or evidence is insufficient.
10. Request usage and non-sensitive execution metadata are recorded.

## 4. Core administrator flow

1. Administrator signs in through a separate authentication flow.
2. Administrator creates a project or edits structured project facts.
3. Administrator uploads a Markdown document in the first MVP.
4. Backend returns `202 Accepted` and a `job_id`.
5. An ingestion process validates, cleans, chunks, embeds, and indexes the document.
6. Administrator previews document/chunk output.
7. Administrator explicitly publishes the document.
8. Only published chunks become available to recruiter retrieval.

## 5. MVP scope

The first usable public release supports:

- one administrator;
- one candidate profile;
- one or two projects;
- Markdown knowledge documents;
- PostgreSQL plus pgvector;
- Redis-backed recruiter sessions and rate limiting;
- separate recruiter and administrator access;
- project-scoped access grants;
- RAG retrieval with source citations;
- evidence-insufficient and out-of-scope responses;
- bounded LangGraph orchestration;
- FastAPI backend;
- a minimal recruiter UI and administrator UI;
- Docker Compose local development;
- deployment to one small public server using remote LLM and embedding APIs.

## 6. Explicit non-goals for the MVP

Do not implement:

- public user registration;
- multiple candidate tenants;
- OCR or scanned PDF ingestion;
- complex table extraction;
- web search;
- voice;
- arbitrary code execution;
- autonomous knowledge editing;
- multi-agent teams;
- Kubernetes;
- microservices;
- billing;
- enterprise SSO.

## 7. Data classification

### Public-after-publication

- candidate display profile;
- project title, summary, technology stack, role, and public links;
- published project explanations;
- published citations.

### Private administrator data

- drafts and unpublished documents;
- raw ingestion errors and review notes;
- access-grant metadata;
- administrator account data;
- internal execution/debug information.

### Secrets

- raw recruiter access tokens;
- administrator password/session secrets;
- model and cloud API keys;
- database and Redis credentials.

Secrets must never enter prompts, logs, source control, citations, or public API responses.

## 8. High-level durable entities

- `admin_users`
- `candidate_profiles`
- `projects`
- `project_facts`
- `documents`
- `document_versions`
- `document_chunks`
- `ingestion_jobs`
- `access_grants`
- `conversations`
- `messages`
- `agent_runs`
- `agent_steps`
- `citations`
- `feedback`

The exact schema should be introduced only when the relevant milestone requires it.

## 9. Delivery phases

### Phase 0 — backend foundation

FastAPI app, settings, logging, lifespan, PostgreSQL and Redis connectivity, health checks, tests, Docker Compose, and development documentation.

### Phase 1 — access control

Recruiter access grants, secure token exchange, Redis sessions, expiry/revocation/quota checks, separate administrator authentication, and authorization tests.

### Phase 2 — project and knowledge management

Project CRUD, Markdown ingestion, job status, chunk preview, publication state, and deletion/replacement correctness.

### Phase 3 — grounded RAG

Embedding/indexing, project-scoped retrieval, metadata filters, citation assembly, refusal behavior, deterministic evaluation examples, and retrieval tests.

### Phase 4 — LangGraph agent

Question scope classification, structured facts versus RAG routing, evidence grading, one bounded retrieval retry, response generation, output validation, and SSE event streaming.

### Phase 5 — production deployment

Container hardening, reverse proxy, HTTPS, backup, migrations, monitoring, rate limits, timeouts, cost caps, and incident-safe logging.

## 10. MVP acceptance criteria

The MVP is acceptable only when:

- no recruiter session can be created from an invalid, expired, revoked, or over-quota grant;
- each grant can be restricted to specific projects;
- unpublished or disallowed chunks never appear in retrieval results;
- administrator endpoints reject recruiter sessions;
- factual public answers contain citations to actual retrieved chunks;
- citations cannot reference chunks that were not retrieved for that run;
- insufficient evidence produces an honest refusal instead of invented experience;
- prompt-injection attempts cannot enable write tools, broaden project scope, or reveal private material;
- PostgreSQL and Redis are not exposed to the public internet;
- service restart preserves durable project, document, grant, and publication data;
- automated tests cover the most important authorization and grounding rules.
