# Phase 2.3 Status — Document processing and chunking

Date: 2026-07-15
Status: completed; stopped before Phase 2.4

Related documentation:

- [Developer learning notes](../learning/PHASE_2_3_LEARNING.md)
- [Architecture diagrams](../architecture/PHASE_2_3_ARCHITECTURE.md)

## 1. Objective

Convert the immutable Markdown document versions saved in Phase 2.2 into deterministic,
structured `document_chunks` through a persistent asynchronous Job and an independent Worker.
The API request path creates and reports work; it does not execute cleaning or chunking.
Successful processing moves a version from `draft` through `processing` to
`ready_for_review`. This is not publication.

## 2. Starting-state checks and scope decision

The implementation started only after reading `AGENTS.md`, `docs/PRODUCT_SPEC.md`,
`docs/RUNTIME_AGENT_HARNESS.md`, `docs/PHASE1_SUMMARY.md`, `docs/PHASE2_PLAN.md`,
`docs/status/PHASE_2_2_STATUS.md`, and the existing models, migrations, administrator and
Recruiter authentication dependencies, Redis adapters, React pages, and tests.

The checks confirmed:

- Phase 2.2 was complete at Git baseline `01a48f2` on `main` and its checkpoint was present.
- `DocumentVersion` contained immutable `raw_content`, a source hash, and draft-only status.
- Administrator routes use `get_current_admin`; administrator and Recruiter Cookies, Redis
  Sessions, principals, and dependencies remain separate.
- Redis was used only for ephemeral Sessions and rate limits; no queue component existed.
- No Celery, RQ, ARQ, Worker, Job table, or Chunk table was present.

`docs/PHASE2_PLAN.md` had a global “no frontend” bullet even though Phase 2.2 and this explicit
Phase 2.3 request included administrator React pages. The explicit confirmed scope was followed,
and the plan now distinguishes forbidden interviewer/Chat frontend work from explicitly scoped
administrator pages. Phase 2.4's text was also adjusted to recognize that Phase 2.3 already
provides read-only Chunk inspection; editing, disabling, approval, and freeze remain Phase 2.4.

## 3. Functionality actually completed

- Persistent ingestion Job creation, lookup, stage/progress updates, failure recording, and
  active-Job idempotency.
- Independent ARQ Worker process backed by Redis; FastAPI only creates/enqueues work and reads
  PostgreSQL state.
- Deterministic Markdown cleaning, empty-content rejection, and SHA-256 computation.
- Markdown-aware heading/paragraph splitting with stable zero-based order and fenced-code
  handling.
- Atomic replacement of a version's Chunks, Job completion, and transition to
  `ready_for_review`.
- Admin-only Job creation/status and read-only Chunk APIs.
- React start action, Job status/progress page, and read-only Chunk page.
- Docker Compose Worker service and local Worker startup documentation.

## 4. New and changed data models

Migration: `alembic/versions/f3a9c2d8e4b1_create_phase_2_3_ingestion.py`.

### `ingestion_jobs`

- UUID `id` primary key;
- `document_version_id` foreign key with delete cascade;
- durable `status`: `pending | processing | completed | failed`;
- separate `stage`: `reading | cleaning | chunking | saving`;
- bounded integer `progress` from 0 through 100;
- nullable safe `error_message`;
- `created_at`, `started_at`, and `finished_at` timestamps;
- indexes for version and status;
- PostgreSQL partial unique index allowing at most one `pending`/`processing` Job per version.

### `document_chunks`

- UUID `id` primary key;
- `document_version_id` foreign key with delete cascade;
- non-negative, per-version unique `chunk_index`;
- JSON `heading_path`;
- `content`, SHA-256 `content_hash`, and `character_count`;
- `enabled` defaults to `true` but is read-only in this phase;
- `created_at` timestamp.

No Embedding, vector, similarity, score, review, publication, or current-published-version
column was added. `DocumentVersion.status` is now constrained to `draft`, `processing`, or
`ready_for_review` only.

## 5. Job flow and PostgreSQL ownership

```text
POST process
  -> lock DocumentVersion
  -> return an existing active Job when present
  -> otherwise atomically create pending Job + set version processing
  -> enqueue only the Job UUID in Redis

Worker
  -> begin: processing / reading / 5
  -> cleaning / 25
  -> chunking / 55
  -> saving / 85
  -> atomically replace Chunks + completed / saving / 100
  -> set version ready_for_review
```

Queue failure marks the Job `failed`, stores a fixed safe message, and restores the version to
`draft`. Empty or unexpected processing failures do the same. Graceful cancellation and ARQ
timeout are handled separately from ordinary exceptions so cancellation first records
`failed` and then propagates. A repeated process request re-enqueues an existing `pending` Job,
closing the recoverable PostgreSQL-commit/Redis-enqueue interruption window; an already
`processing` Job is not duplicated.

PostgreSQL is the sole source for status queries and Chunk reads. Redis contains an ephemeral
ARQ message with a Job UUID and is never the only copy of business state.

## 6. Worker architecture and queue choice

ARQ 0.28 was selected over Celery and RQ because this milestone needs one small asyncio-native
Redis queue, one async function, bounded concurrency, and no multi-broker workflow framework.
It integrates directly with the project's async PostgreSQL and Redis stack while keeping the
Worker independent from FastAPI. The Worker has its own database pool and lifecycle, uses a
dedicated queue name, JSON rather than pickle serialization, two concurrent jobs, a 300-second
timeout, one attempt, no retained result, and a shutdown grace period.

Celery would add a larger framework and configuration surface not used by this slice. RQ is
primarily synchronous and would require additional bridging around the existing async database
path.

## 7. Deterministic cleaning rules

`app/ingestion/cleaning.py` performs only:

1. removal of an initial UTF-8 BOM;
2. removal of NUL characters;
3. CRLF and CR normalization to LF;
4. removal of trailing spaces and tabs on each line;
5. compression of consecutive blank lines to one blank line;
6. full-document boundary trimming;
7. failure when the cleaned result is empty; and
8. SHA-256 calculation over the cleaned UTF-8 content.

It performs no LLM call, rewriting, inference, correction, or content supplementation.

## 8. Chunk design

`app/ingestion/chunking.py` recognizes ATX headings outside fenced code. The first level-one
heading is treated as the document title and omitted from `heading_path`, matching the confirmed
example; its line remains in Chunk content. Descendant headings form an ordered path such as
`["技术架构", "Worker"]`.

Sections are split first by heading, then—only when a section exceeds the configured target—at
paragraph boundaries. Each secondary Chunk repeats its section heading for context. A single
indivisible long paragraph or fenced block is preserved and is never hard-cut at an arbitrary
character. Opening and closing fences are recognized outside headings, including a valid closing
fence longer than its opening fence. `chunk_index` is assigned deterministically from zero in
source order. Each saved Chunk has its own SHA-256 hash and exact character count.

## 9. Administrator APIs

All routes use `get_current_admin`:

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/v1/admin/document-versions/{version_id}/process` | `202` with `job_id` and current Job status. |
| `GET` | `/api/v1/admin/jobs/{job_id}` | Durable status, stage, progress, safe error and document context. |
| `GET` | `/api/v1/admin/document-versions/{version_id}/chunks` | Stable ordered read-only Chunk list. |

Missing resources use sanitized 404 responses, already-ready versions use 409, and PostgreSQL,
Redis, queue, and timeout failures use the existing machine-readable sanitized 503 shape. A
Recruiter Session cannot authenticate to these administrator routes.

## 10. Administrator frontend

- The selected draft version on the document detail page has a **开始处理** button.
- The Job page at `/admin/jobs/:jobId` displays document name/version, all raw Job status values,
  localized stage, progress bar, safe failure text, polling while active, and explicit retry
  after a transient query failure.
- Completed Jobs link to `/admin/document-versions/:versionId/chunks`.
- The Chunk page displays `chunk_index`, slash-joined `heading_path`, character count, and literal
  content in `<pre>`.
- 401 responses redirect to the administrator login page.

No Chunk editor, enabled toggle, review/approval control, Embedding state, or publish action was
added.

## 11. Files added and modified

Main backend additions:

- `app/models/ingestion_job.py`, `app/models/document_chunk.py`;
- `app/repositories/ingestion.py`;
- `app/services/ingestion.py`, `app/services/ingestion_worker.py`;
- `app/ingestion/cleaning.py`, `app/ingestion/chunking.py`;
- `app/infrastructure/job_queue.py`, `app/worker.py`;
- `app/api/routes/admin_ingestion.py`, `app/schemas/ingestion.py`;
- the Phase 2.3 Alembic migration.

Main integration and frontend changes:

- `app/main.py`, model/schema/config exports, API exceptions, `.env.example`;
- `docker-compose.yml`, `pyproject.toml`, `uv.lock`;
- `frontend/src/pages/DocumentDetail.tsx`, `IngestionJob.tsx`, `DocumentChunks.tsx`;
- frontend API/types/router and matching tests;
- backend model, migration, cleaning, chunking, repository, service, Worker, queue, API, and
  configuration tests;
- `README.md`, `docs/PHASE2_PLAN.md`, design/implementation records, this checkpoint, and the
  concise `AGENTS.md` status;
- `docs/learning/PHASE_2_3_LEARNING.md` and
  `docs/architecture/PHASE_2_3_ARCHITECTURE.md` for closure learning and Mermaid diagrams.

## 12. Verification actually run

### 12.1 Closure revalidation on 2026-07-15

- `uv run ruff check .` -> exit 0, `All checks passed!`.
- `uv run ruff format --check .` -> exit 0, `97 files already formatted`.
- `uv run pytest -q` -> exit 0, `317 passed in 37.78s`.
- `uv run alembic upgrade head` -> exit 0.
- `uv run alembic check` -> exit 0, `No new upgrade operations detected.`
- `npm run lint` in `frontend/` -> exit 0.
- `npm run typecheck` in `frontend/` -> exit 0.
- `npm test` in `frontend/` -> exit 0, `11 passed` test files and `59 passed` tests.
- `npm run build` in `frontend/` -> exit 0; Vite transformed 48 modules and produced the
  production bundle in 238 ms.
- `docker compose ps` -> exit 0; backend and Worker were running, PostgreSQL and Redis were
  healthy.
- `docker compose logs --no-color --tail 40 worker` -> exit 0; logs showed the ARQ Worker had
  started and had successfully consumed `process_document_version_job`.

### 12.2 Real API/Worker flow from Phase 2.3 implementation verification

Real API/Worker flow with fictional temporary data:

```text
administrator login                         -> 200
create Project                              -> 201
create pasted Markdown document             -> 201
POST process                                -> 202 / pending
independent ARQ Worker invocation            -> success
final Job                                   -> completed / saving / 100
DocumentVersion                             -> ready_for_review
GET Chunks                                  -> 3 Chunks, indexes [0, 1, 2]
last heading_path                           -> ["Architecture", "Worker"]
administrator logout                        -> 204
```

Worker logs showed `process_document_version_job` consumed and completed in a separate Compose
service. The script removed its temporary administrator, Project, document, version, Job, and
Chunks. No real browser automation was run; frontend behavior was verified by jsdom tests and the
production build, and no browser-test claim is made.

## 13. Current usable capability

An authenticated administrator can save Markdown, start asynchronous processing, leave the API
request immediately with a persistent Job UUID, inspect durable progress/failure state, wait for
an independent Worker to clean and split the document, and read the resulting ordered Chunks.
Successful processing ends at `ready_for_review`; unpublished material remains outside all
Recruiter/public retrieval paths.

```text
Administrator login
→ select a DocumentVersion
→ create a persistent IngestionJob
→ independent Worker processes in the background
→ generate ordered DocumentChunks
→ inspect Job status and read-only Chunk output
```

## 14. Explicitly unimplemented

- Chunk review or approval;
- publication workflow;
- Embedding;
- pgvector integration or vector columns;
- RAG;
- Retriever;
- LangGraph;
- Chat;
- SSE.

No item in this list should be inferred from the existence of `ready_for_review` or the read-only
Chunk page.

## 15. Known limitations and non-blocking issues

- This first queue slice deliberately has no transactional outbox. A hard API crash after the Job
  commit but before Redis enqueue can temporarily strand a `pending` record; repeating the
  process request safely re-enqueues it.
- Graceful Worker cancellation/timeout records failure. A process hard-kill cannot run cleanup
  and may leave a stale `processing` Job; there is no lease sweeper or administrative recovery
  endpoint in this milestone.
- ARQ attempts each Job once. Repeating the process request for a failed version creates a new
  Job; there is no automatic retry policy.
- The 2,000-character target is not a hard cap because semantic paragraphs and fenced blocks are
  kept intact.
- Only ATX Markdown headings are structurally recognized in this first splitter.
- The public/interviewer agent still has no access to these unpublished Chunks.

These limitations do not justify adding Phase 2.4 or later frameworks early.

## 16. Git status and diff summary

- Branch: `main`.
- Baseline HEAD: `01a48f2 feat: complete Phase 2.2 knowledge documents and versions`.
- Working tree: intentionally dirty with the complete, uncommitted Phase 2.3 implementation and
  checkpoint; no Commit, Tag, Push, or Merge was performed.
- Current `git status --short` contains 47 entries: modified tracked files plus the new migration,
  backend, frontend, tests, design/plan, and status files. The tracked diff shows 20 files changed,
  472 insertions, and 34 deletions; untracked additions are listed separately by `git status` and
  are not included in that tracked-only statistic.
- `git diff --check` exited 0. Git emitted only Windows line-ending and inaccessible user-level
  global-ignore warnings; no whitespace error was reported.

Commands and current results:

```text
git branch --show-current
main

git status --short
47 entries: 20 modified tracked paths and 27 untracked status entries

git diff --stat
20 files changed, 472 insertions(+), 34 deletions(-)
```

The 30 individual untracked files reported by `git ls-files --others --exclude-standard` include
the Phase 2.3 migration, backend modules, frontend pages, tests, design/plan, status, learning,
and architecture documents. The difference between 27 untracked status entries and 30 files is
caused by `git status --short` collapsing untracked directories.

Git preparation safety checks found:

- `.env` is not tracked and is ignored;
- zero Redis dump or database backup artifacts;
- zero files matching the high-confidence private-key, common API-key, GitHub token, Slack token,
  AWS access-key, or JWT patterns used by the closure scan;
- only the documented safe placeholders remain in `.env.example` and Docker Compose defaults.

## 17. Relative change from Phase 2.2

Phase 2.2 stopped after storing immutable, original Markdown versions in `draft`. Phase 2.3 adds
the first persistent processing state machine, independent queue Worker, deterministic normalized
processing, structured Chunk persistence, progress/status visibility, and read-only administrator
inspection. It does not change recruiter authorization, publish any content, or make Chunks
retrievable by a public agent.

## 18. Next subsection boundary

Phase 2.4 may begin only after explicit user confirmation. Subject to that confirmation, its
smallest allowed scope is Chunk review/freeze behavior such as administrator disable/enable and
review confirmation based on the existing read-only Chunks.

Phase 2.4 and later behavior is explicitly forbidden from being implemented early. This means no:

- Chunk editing, disable/enable mutation, review approval, or freeze state in this checkpoint;
- automatic publication, `published`, or `superseded` state;
- Embedding or Embedding status;
- pgvector or vector columns;
- Retriever, RAG, LangGraph, Chat, or SSE;
- PDF, Word, OCR, web scraping, or LLM cleaning.

ResumeGraph is stopped at the Phase 2.3 checkpoint and awaits explicit confirmation.
