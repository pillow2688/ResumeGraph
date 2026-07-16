# ResumeGraph

This repository has completed the **Phase 4 multi-agent interview workflow** on top of the
published Profile and Grant-scoped Project RAG baseline. An authorized Recruiter can use the
chat-style `/interview` page for a bounded multi-turn conversation. A LangGraph Supervisor routes
questions to Profile, Project, and Technical specialists, then a Verification Agent checks factual
and authorization boundaries before the response is returned through a normal API or public SSE
progress stream. PostgreSQL remains the durable authorization and knowledge source; pgvector
performs retrieval, while Redis stores only ephemeral sessions, conversations, rate-limit counters,
and the ARQ queue.

The approved Embedding configuration is 智谱 `embedding-3`, 1024 dimensions, batch size 10,
30-second timeout, and two retries. The API key is intentionally absent from Git and must be
provided through `EMBEDDING_API_KEY`. On 2026-07-16, real 智谱/DeepSeek calls,
PostgreSQL/pgvector, Redis Conversation, LangGraph, Docker Desktop, POST SSE, and the five-service
Compose stack passed acceptance. A real desktop and mobile browser run verified Profile, Project,
Technical, and planned Evidence boundaries, public Agent progress, scoped Citations, quota, and
immediate Conversation invalidation after Grant revocation.

See the [Phase 4 plan](docs/PHASE4_PLAN.md), [Phase 4 summary](docs/PHASE4_SUMMARY.md),
[Phase 4 status](docs/status/PHASE_4_STATUS.md),
[learning notes](docs/learning/PHASE_4_LEARNING.md), and
[architecture](docs/architecture/PHASE_4_ARCHITECTURE.md). Phase 5 evaluation and advanced
retrieval are not started.

## Phase 4 multi-agent interview workflow

Phase 4 adds administrator-published Technical knowledge and explicitly separates four Evidence
identities: Profile facts, implemented Project facts, planned Project solutions, and general
Technical knowledge. Technical material explains principles but cannot prove that a mechanism was
implemented in a Project; planned material is presented only as a future option.

The bounded LangGraph workflow contains five Agents with independent prompts, strict Pydantic
inputs and outputs, private tool allowlists, and code-enforced budgets:

```text
Interview Supervisor
├─ Profile Agent      → published Profile knowledge
├─ Project RAG Agent  → currently authorized Project knowledge
├─ Technical Agent    → published general Technical knowledge
└─ Verification Agent → citation, publication, Grant, and semantic-boundary checks
```

The Phase 3 compatibility route remains available at `POST /api/v1/interview/ask`. Phase 4 adds:

- `POST /api/v1/interview/conversations`
- `POST /api/v1/interview/conversations/{conversation_id}/ask`
- `POST /api/v1/interview/conversations/{conversation_id}/ask/stream`
- `DELETE /api/v1/interview/conversations/{conversation_id}`

Conversation history is short-lived Redis context used only for reference resolution. Every turn
revalidates the Recruiter Session, Grant, current Project scope, published Evidence, and citation
handles. Historical answers never become factual Evidence. The React page provides right-aligned
interviewer messages, left-aligned Markdown answers, public Agent progress, expandable citations,
desktop/mobile drawers, interruption handling, and no localStorage chat persistence.

## Phase 3 RAG MVP

Candidate background is stored as published Profile documents. Every valid Recruiter Grant can
retrieve published Profile evidence, while Project evidence is still restricted by the Grant and
the request's selected-project intersection. Profile and Project evidence rank together in one
pgvector Top-K query and expose their scope explicitly in Citations.

```text
Recruiter Session revalidation
→ requested Projects ∩ currently allowed Projects
→ atomic request_count UPDATE ... RETURNING
→ shared EmbeddingProvider.embed_query
→ authorized current-published pgvector Top-K
→ server-owned Evidence handles
→ strict JSON first-person answer or fixed refusal
→ citation revalidation and minimal public response
```

The public route is `POST /api/v1/interview/ask`. Invalid parameters, invalid Sessions, and empty
project intersections do not consume quota. Once a valid request reserves quota, insufficient
evidence and temporary Provider failures are not refunded. The React page keeps visible turns only
in component memory and never sends history with the next request.

Administrator management uses `GET/POST /api/v1/admin/users` and
`DELETE /api/v1/admin/users/{admin_user_id}`. The UI at `/admin/users` prevents self-deletion, while
the backend also prevents deleting the final administrator. Project and Profile knowledge pages
show the required upload → process → Chunk review → index → publish workflow; uploading alone does
not make a document retrievable.

## Architecture

The application is built by `app.main.create_app`. Its FastAPI lifespan creates one async
SQLAlchemy engine and one async Redis client when the process starts, stores them on
`app.state`, and closes both when the process stops. Route handlers reuse those objects;
they never create a connection pool or client per request.

- `GET /api/v1/health/live` checks only whether the HTTP process can respond. It remains
  healthy during a temporary database or Redis outage.
- `GET /api/v1/health/ready` concurrently awaits PostgreSQL and Redis probes. Each probe has
  the short timeout configured by `RESUMEGRAPH_READINESS_TIMEOUT_SECONDS`. The endpoint
  returns `503` until both dependencies are available.
- Infrastructure adapters translate driver failures into a sanitized internal error. API
  responses contain only `up`/`down` dependency state, never driver messages, credentials,
  DSNs, or stack traces.

`async`/`await` matters on the readiness path because database and Redis probes perform
network I/O. Awaiting the async drivers lets FastAPI serve other requests while those probes
wait. The liveness handler is synchronous because it performs no awaitable I/O.

## Phase 1.1 data model

SQLAlchemy models live in `app/models/`, while PostgreSQL schema changes remain owned by
Alembic. The first migration creates:

- `admin_users`, with a unique administrator username and password hash;
- `projects`, containing the project name and description;
- `access_grants`, containing only a token digest, expiry, request limits, usage count, and
  nullable revocation timestamp;
- `grant_projects`, a composite-primary-key association table implementing project-scoped
  many-to-many grants.

The database never stores a raw recruiter access token. A `NULL` `revoked_at` means that a
grant has not been revoked; a non-null value records when revocation occurred. Deleting a grant
removes its association rows. Project deletion goes through the Project service, which refuses
to delete a project referenced by either an Access Grant or a Knowledge Document; it does not
use the association table's database cascade to silently shrink scope.

`created_at` and `updated_at` receive database defaults. SQLAlchemy's `onupdate` refreshes
`updated_at` on normal ORM-generated updates. There is deliberately no database trigger in
this phase, so direct SQL updates must set `updated_at` explicitly when that behavior is
required.

## Phase 1.2 administrator authentication

The administrator and recruiter authentication systems are separate. There is no public
administrator registration endpoint. An operator creates the first administrator with the
CLI; the password is read through `getpass`, hashed with pwdlib's recommended Argon2
configuration, and never printed, logged, or stored as plaintext.

```text
CLI -> AdminAccountService -> AdminUserRepository -> PostgreSQL

POST /api/v1/admin/auth/login
  -> normalize username
  -> check the Redis failure limiter
  -> load the administrator from PostgreSQL
  -> verify the Argon2 password hash
  -> store a fixed-expiry Redis session under a SHA-256-digested key
  -> return the opaque token only in an HttpOnly cookie

GET /api/v1/admin/auth/me
  -> read and digest the cookie token
  -> load the Redis session
  -> re-load the administrator from PostgreSQL
  -> return only id and username
```

Redis stores only `admin_id`, `username`, `created_at`, and `expires_at`. The username in
Redis is informational: `/me` trusts the current PostgreSQL record. Reading a session never
extends its TTL.

Logout is intentionally idempotent. `POST /logout` deletes the digest-keyed Redis session
when a cookie is present and always clears the browser cookie. A missing or already-invalid
cookie therefore returns `204`; a Redis failure while deleting a presented session returns a
sanitized `503` because the server-side session may still exist.

## Phase 1.3 recruiter access grants and sessions

An authenticated administrator can create, list, inspect, and revoke a project-scoped
Access Grant:

```text
POST /api/v1/admin/access-grants
  -> validate expiry, request limit, and one or more existing project IDs
  -> generate rsg_<high-entropy random content> with Python secrets
  -> store only HMAC-SHA256(token, ACCESS_TOKEN_PEPPER) in PostgreSQL
  -> create the grant and all grant_projects rows in one transaction
  -> return the raw access_token in this successful response only
```

`access_token` is displayed only once. If it is lost, it cannot be recovered; revoke that
grant and create a replacement. The database digest supports lookup without retaining the
bearer credential. List, detail, revoke, logs, Redis, and error responses never include the
raw token or its digest.

With an administrator cookie and an existing project UUID, create a grant as follows. Save
the returned token in memory only; do not paste it into logs or shell history.

```powershell
$GrantBody = @{
  name = "Fictional Company - Interview"
  expires_at = "2026-08-31T15:59:59Z"
  max_requests = 100
  project_ids = @("<existing-project-uuid>")
} | ConvertTo-Json

$Created = Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/admin/access-grants `
  -Method Post `
  -ContentType application/json `
  -Body $GrantBody `
  -WebSession $AdminSession
```

The recruiter exchanges the token in a JSON `POST` body, receives a separate HttpOnly
cookie, views the current PostgreSQL-backed scope, and logs out:

```powershell
$ExchangeBody = @{ access_token = $Created.access_token } | ConvertTo-Json
Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/v1/access/exchange `
  -Method Post `
  -ContentType application/json `
  -Body $ExchangeBody `
  -SessionVariable RecruiterSession

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/access/me `
  -WebSession $RecruiterSession

Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/v1/access/logout `
  -Method Post `
  -WebSession $RecruiterSession
```

URL query tokens are deliberately unsupported because query strings can enter browser
history, access logs, proxy logs, and `Referer` headers. The exchange endpoint reads only
the JSON request body.

The recruiter session has a fixed, non-sliding TTL equal to the smaller of
`RESUMEGRAPH_RECRUITER_SESSION_TTL_SECONDS` and the grant's remaining lifetime. Its Redis
payload includes `grant_id`, creation/expiry times, and a project-ID snapshot used only for
diagnostics. Every protected request reloads the grant and its current projects from
PostgreSQL, then rechecks expiry, revocation, quota exhaustion, and non-empty scope. This is
why revoking a grant immediately rejects its old recruiter sessions without scanning Redis.

`POST /api/v1/access/exchange` counts failed attempts per `request.client.host` in Redis;
the default allows 10 failed responses in 10 minutes and returns `429` on subsequent
attempts. Success clears that IP's counter. Redis failure returns a sanitized `503` rather
than silently bypassing the limiter. Client-supplied `X-Forwarded-For` is not trusted. A
production deployment behind a trusted reverse proxy must establish one reviewed proxy-IP
policy before using forwarded client addresses.

The token exchange rejects an already exhausted Grant. `/access/me` and `/interview` can still
represent a current zero-quota Session so the UI can show the exhausted state. Each valid Interview
request consumes quota with one conditional database `UPDATE ... RETURNING`, never a `SELECT`
followed by a Python-side increment.

To inspect and revoke grants with the administrator cookie:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/admin/access-grants `
  -WebSession $AdminSession

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/admin/access-grants/<grant-uuid>/revoke" `
  -Method Post `
  -WebSession $AdminSession
```

## Phase 2.1 administrator Project CRUD

All Project management routes reuse the existing `get_current_admin` dependency and are
available under `/api/v1/admin/projects`:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/api/v1/admin/projects` | Create a project and return `201`. |
| `GET` | `/api/v1/admin/projects` | List all projects by `created_at DESC, id DESC`. |
| `GET` | `/api/v1/admin/projects/{project_id}` | Return one project or `project_not_found`. |
| `PATCH` | `/api/v1/admin/projects/{project_id}` | Update one or both editable fields. |
| `DELETE` | `/api/v1/admin/projects/{project_id}` | Delete an unused project and return an empty `204`. |

Names and descriptions are trimmed at the request boundary and again in the service. Names
must contain 1–200 characters; descriptions may be empty and are limited to 5,000 characters.
PATCH rejects an empty body and explicit `null` values. A PATCH whose normalized values equal
the stored values is a no-op, so SQLAlchemy does not issue an UPDATE and `updated_at` remains
unchanged.

Deletion is deliberately stricter than the Phase 1 foreign key. The repository locks the
Project row, checks `grant_projects` and `knowledge_documents`, and deletes only an unreferenced
project in the same transaction. A referenced project returns `409 project_in_use`; it never relies on
`ON DELETE CASCADE` to silently shrink an existing Access Grant. Project CRUD does not read or
write Redis and does not change Grant quota, expiry, usage, or revocation state.

Phase 2.1 reuses the existing `projects` table without schema changes, so it adds no Alembic
Migration. `uv run alembic check` is the metadata-consistency check for this subsection.

## Phase 2.2 knowledge documents and versions

Migration `d7f6a2b4c8e1` adds `knowledge_documents` and `document_versions`. A document belongs to
one Project; a version belongs to one document and is immutable after creation. PostgreSQL
enforces positive version numbers, draft-only status, valid source types, unique
`(document_id, version_number)`, and unique `(document_id, content_hash)`.

All routes reuse `get_current_admin`:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/api/v1/admin/projects/{project_id}/documents` | Create a document and pasted-Markdown v1; return `201`. |
| `POST` | `/api/v1/admin/projects/{project_id}/documents/upload` | Create a document and uploaded `.md` v1; return `201`. |
| `GET` | `/api/v1/admin/projects/{project_id}/documents` | List document summaries and their latest version without full content. |
| `GET` | `/api/v1/admin/documents/{document_id}` | Return document, Project summary, version count, and latest version. |
| `PATCH` | `/api/v1/admin/documents/{document_id}` | Change only the document title. |
| `POST` | `/api/v1/admin/documents/{document_id}/versions` | Add a pasted draft version; return `201`. |
| `POST` | `/api/v1/admin/documents/{document_id}/versions/upload` | Add an uploaded `.md` draft version; return `201`. |
| `GET` | `/api/v1/admin/documents/{document_id}/versions` | List version summaries newest first. |
| `GET` | `/api/v1/admin/document-versions/{version_id}` | Return one version including its original Markdown. |

The service creates a document and v1 in one transaction. New-version transactions lock the
parent document row, reject an existing SHA-256 content hash, and then allocate the next version
number from the current maximum; database unique constraints are the final concurrency guard.
List queries use a windowed latest-version query and byte-length projection, avoiding N+1 reads
and avoiding full Markdown content in summary responses.

Pasted and uploaded content share the configured `RESUMEGRAPH_MARKDOWN_MAX_BYTES` limit (default
1 MiB). Content must be nonblank UTF-8, may have a UTF-8 BOM removed, and may not contain NUL.
Uploads must have a `.md` filename; only a safe basename is persisted, and content is never
written to an arbitrary server path. The administrator UI is available at
`/admin/projects/:projectId/documents` and `/admin/documents/:documentId`; Markdown is rendered as
literal text in `<pre>`, without `dangerouslySetInnerHTML` or raw HTML execution.

## Phase 2.3 asynchronous processing and chunking

Migration `f3a9c2d8e4b1` adds persistent `ingestion_jobs` and `document_chunks`, and extends the
version state machine to `draft -> processing -> ready_for_review`. Job status and current stage
are separate: status is `pending`, `processing`, `completed`, or `failed`; stage is `reading`,
`cleaning`, `chunking`, or `saving`. PostgreSQL stores all durable status and Chunk data. Redis
only delivers an ARQ message containing the Job UUID.

The API process creates or recovers a pending Job and returns `202`; it never cleans or chunks
the document in the request path. Run the independent Worker with:

```powershell
uv run arq app.worker.WorkerSettings
```

The Worker removes an initial UTF-8 BOM and all NUL characters, normalizes newlines, trims line
ends and the document boundary, compresses consecutive blank lines, rejects content that becomes
empty, and computes a SHA-256 hash. Markdown-aware splitting follows ATX heading hierarchy and
paragraph boundaries while keeping fenced code intact. `RESUMEGRAPH_CHUNK_MAX_CHARACTERS`
(default `2000`) is a paragraph-aware secondary-split target; a single indivisible paragraph is
preserved even when it exceeds that target.

All Phase 2.3 APIs reuse `get_current_admin`:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/api/v1/admin/document-versions/{version_id}/process` | Create/recover a Job and return `202`. |
| `GET` | `/api/v1/admin/jobs/{job_id}` | Read durable status, stage, progress, and safe failure text. |
| `GET` | `/api/v1/admin/document-versions/{version_id}/chunks` | List stored Chunks by stable `chunk_index`. |

The React administrator UI adds a **开始处理** action, a polling Job page at
`/admin/jobs/:jobId`, and a read-only Chunk page at
`/admin/document-versions/:versionId/chunks`. Chunk content is still rendered only as literal
text. Processing success is preparation for a future review phase, never automatic publication.

Phase 2.4 extends the same administrator surface with the following generic APIs:

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/api/v1/admin/document-versions/{version_id}/index` | Create/recover the single active knowledge-indexing Job. |
| `PATCH` | `/api/v1/admin/document-chunks/{chunk_id}` | Correct the final `enabled` switch and require re-indexing. |
| `GET` | `/api/v1/admin/embedding-config` | Show non-secret active Embedding configuration. |
| `POST` | `/api/v1/admin/document-versions/{version_id}/publish` | Publish only with a complete active-config Embedding set. |
| `DELETE` | `/api/v1/admin/documents/{document_id}/publication` | Take the document offline. |

The Chunk page shows rule/DeepSeek summaries, warnings, metadata, the active generic Embedding
configuration, and a simple enabled switch. The Job page shows `rule_check`,
`llm_quality_check`, `embedding`, and `saving`; the document page shows the current published
version and publish/offline actions.

Recruiter settings:

- `RESUMEGRAPH_ACCESS_TOKEN_PEPPER`: deployment secret used only for token HMAC; the
  example value is a local placeholder and production rejects it;
- `RESUMEGRAPH_RECRUITER_SESSION_COOKIE_NAME`: default
  `resumegraph_recruiter_session`, required to differ from the admin cookie;
- `RESUMEGRAPH_RECRUITER_SESSION_TTL_SECONDS`: default `14400` seconds (4 hours);
- `RESUMEGRAPH_ACCESS_EXCHANGE_FAILURE_LIMIT`: default `10` failures;
- `RESUMEGRAPH_ACCESS_EXCHANGE_FAILURE_WINDOW_SECONDS`: default `600` seconds.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose for local PostgreSQL/pgvector and Redis

## Local setup

Create a local environment file from the safe example. The real `.env` is ignored by Git.

```powershell
Copy-Item .env.example .env
uv sync
```

Start only the dependencies, then run the API on the host:

```powershell
docker compose up -d postgres redis
uv run uvicorn app.main:app --reload
```

Run the independent Worker in a second terminal:

```powershell
uv run arq app.worker.WorkerSettings
```

Apply migrations and create the initial administrator. The CLI prompts twice without echoing
the password; plaintext passwords cannot be supplied as command-line arguments.

```powershell
uv run alembic upgrade head
uv run python -m app.cli.create_admin --username admin
```

Alternatively, build and run the complete development stack:

```powershell
docker compose up --build
```

The Compose file is for local development. PostgreSQL, Redis, and the backend bind only to
`127.0.0.1`; a production deployment must not publish PostgreSQL or Redis ports at all.

## Verify health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready
```

Successful readiness response:

```json
{
  "status": "ready",
  "dependencies": {"postgresql": "up", "redis": "up"}
}
```

When a dependency is unavailable, readiness returns HTTP `503` with the consistent error
shape documented by the OpenAPI schema. Liveness still returns HTTP `200`.

## Use administrator authentication

The following PowerShell flow keeps the password out of the command line and preserves the
session cookie in memory:

```powershell
$Credential = Get-Credential -UserName admin
$LoginBody = @{
  username = $Credential.UserName
  password = $Credential.GetNetworkCredential().Password
} | ConvertTo-Json

Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/v1/admin/auth/login `
  -Method Post `
  -ContentType application/json `
  -Body $LoginBody `
  -SessionVariable AdminSession

Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/v1/admin/auth/me `
  -WebSession $AdminSession

Invoke-WebRequest `
  -Uri http://127.0.0.1:8000/api/v1/admin/auth/logout `
  -Method Post `
  -WebSession $AdminSession
```

The administrator cookie is HttpOnly, `SameSite=Lax`, and scoped to `/api/v1/admin`. Local
plain-HTTP development uses `RESUMEGRAPH_COOKIE_SECURE=false`. Production configuration is
rejected unless `RESUMEGRAPH_COOKIE_SECURE=true`, and production must serve the application
over HTTPS.

Authentication settings:

- `RESUMEGRAPH_ADMIN_SESSION_COOKIE_NAME`: cookie name; default
  `resumegraph_admin_session`;
- `RESUMEGRAPH_ADMIN_SESSION_TTL_SECONDS`: fixed Redis and cookie lifetime; default `28800`
  seconds (8 hours);
- `RESUMEGRAPH_COOKIE_SECURE`: `false` for local HTTP only, mandatory `true` in production;
- `RESUMEGRAPH_ADMIN_LOGIN_MAX_FAILURES`: default `5`;
- `RESUMEGRAPH_ADMIN_LOGIN_WINDOW_SECONDS`: default `300` seconds.
- `RESUMEGRAPH_DEPENDENCY_TIMEOUT_SECONDS`: PostgreSQL/Redis authentication-operation
  deadline and driver timeout; default `3` seconds.

Failed logins are limited by normalized username plus `request.client.host`. The combined
identifier is SHA-256 digested before becoming a Redis key. Client-supplied
`X-Forwarded-For` is not trusted in this phase.

## Tests and quality checks

Unit tests use deterministic fake dependencies and model metadata; they do not require Docker
or internet access. Migration verification must still run against the real local PostgreSQL
container.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

To exercise real dependency connections, start `postgres` and `redis`, run the API, and call
the readiness endpoint as shown above. This is a documented manual integration check, not
part of the isolated unit suite.

## Alembic

Alembic is configured for the same async database URL as the application and imports the
shared model metadata. Apply and inspect the current revision with:

```powershell
uv run alembic upgrade head
uv run alembic current
```

For a disposable local database that has first been confirmed to contain no important data,
the migration reversal check is:

```powershell
uv run alembic downgrade base
uv run alembic upgrade head
```

## Current limitations

The final Phase 2 lifecycle patch adds `document_scope=profile|project`, Profile document creation
and listing, exact-hash deduplication in current-published Profile or single-Project scopes,
separate unpublish/permanent-delete behavior, safe Version deletion, database cascades, and
canonical/Embedding reselection. Administrator endpoints added by this closure are:

| Method | Path | Responsibility |
| --- | --- | --- |
| `POST` | `/api/v1/admin/profile-documents` | Create a Profile-global document from pasted Markdown. |
| `POST` | `/api/v1/admin/profile-documents/upload` | Create a Profile-global document from an uploaded `.md`. |
| `GET` | `/api/v1/admin/profile-documents` | List Profile documents and current publication/Chunk/Embedding counts. |
| `DELETE` | `/api/v1/admin/document-versions/{version_id}` | Permanently delete an allowed non-current Version and its dependent data. |
| `DELETE` | `/api/v1/admin/documents/{document_id}` | Permanently delete a document after an exact-title JSON confirmation and remove all dependent data. |

The React administrator route `/admin/profile-documents` exposes multiple Profile documents,
statistics, shared Version/processing/indexing/publication workflows, offline confirmation, and
typed permanent deletion. It is not a Recruiter interview or retrieval page.

Phase 2.4 uses a single `OpenAICompatibleEmbeddingProvider`; it does not contain vendor-specific
Provider classes or a multi-vendor factory. If `EMBEDDING_API_KEY` is empty, production startup
uses an explicit `UnconfiguredEmbeddingProvider` and indexing fails safely—never by silently
falling back to the Fake Provider. To run the opt-in live boundary after injecting the secret:

```powershell
$env:RESUMEGRAPH_RUN_LIVE_EMBEDDING='1'
$env:EMBEDDING_API_KEY='set-outside-git'
uv run pytest -q tests/test_phase_2_4_postgres_integration.py -k live
```

The non-billable real PostgreSQL/pgvector publication boundary can be run with
`RESUMEGRAPH_RUN_POSTGRES_INTEGRATION=1` and uses fictional data that is removed by the test.
The live boundary was executed successfully on 2026-07-15 with secrets loaded from the ignored
local `.env`; no API key is stored in this repository.

Phase 4 now adds the bounded LangGraph multi-agent runtime, Technical knowledge, Redis-backed
short-term context, POST SSE, and a chat-style interview UI. It deliberately does not add permanent
chat history, Web Search, Query Rewrite beyond the Project Agent's single bounded retry, Hybrid
Search, BM25, RRF, Reranker, Recall@K/MRR/NDCG evaluation, PDF, Word, OCR, or object storage. A
graceful Worker cancellation records `failed`, but a process hard-kill cannot run cleanup and may
leave a stale `processing` record; there is no lease sweeper or outbox framework. JWT, OAuth,
refresh tokens, recruiter accounts, and email invitations also remain outside the current scope.
Administrator, Recruiter UI, and API deployment should remain same-origin; broad CORS is
intentionally not configured.
