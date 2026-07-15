# Phase 2.4 Status — Minimal knowledge quality, indexing, and publication MVP

Date: 2026-07-15
Status: completed; stopped before retrieval, RAG, Retriever, or LangGraph

Related documentation:

- [Phase 2 final implementation route](../PHASE2_PLAN.md)
- [Phase 2 summary](../PHASE2_SUMMARY.md)
- [Phase 2.4 learning notes](../learning/PHASE_2_4_LEARNING.md)
- [Phase 2.4 architecture](../architecture/PHASE_2_4_ARCHITECTURE.md)

## 1. Objective and corrected scope

Phase 2.4 converts the Chunks produced by Phase 2.3 into reviewed, vectorized, explicitly
published knowledge through one bounded asynchronous workflow. The work was deliberately reduced
to the smallest useful MVP: deterministic safety rules, one strict DeepSeek judgment contract,
one generic OpenAI-compatible Embedding adapter, pgvector persistence, administrator correction,
and atomic publication state.

The abandoned design was removed or not implemented. There is no
`chunk_quality_evaluations` history table or model, numeric `quality_score`, prompt-version
management, persisted token/latency telemetry, three-state override approval system, independent
quality-report platform, multidimensional scoring schema, vendor-specific Embedding Provider
class, multi-vendor factory, quality dashboard, or per-Chunk approval workflow. Tests that served
only those designs were removed; reusable validation and safety coverage was retained.

## 2. Functionality actually completed

- `app/quality/rules.py` runs before any LLM call. It detects secret-like content, duplicate
  content, PII contacts, and unusually long Chunks. Secrets are hard-blocked and are never sent to
  an external model. Phone numbers and email addresses are retained as warnings, redacted before
  external processing, and default the Chunk to disabled. `too_long` remains a normal warning.
- DeepSeek V4 Pro uses an OpenAI-compatible asynchronous client, `temperature=0`, JSON output,
  finite timeout/retry limits, and thinking disabled. Its strict Pydantic schema rejects extra,
  missing, invalid, or duplicate fields and rejects a response whose Chunk IDs do not exactly
  match the server-owned current batch. Chain of thought is neither requested nor persisted.
- `EmbeddingProvider` is the business boundary. `OpenAICompatibleEmbeddingProvider` is the only
  real adapter; `FakeEmbeddingProvider` is deterministic for tests and
  `UnconfiguredEmbeddingProvider` fails safely in production when no key is supplied. Business
  services and Workers do not depend on a vendor SDK or vendor-specific class.
- The real adapter owns one shared async client, supports custom `base_url`, optionally sends
  `dimensions`, restores response order by `data[index]`, and validates result count, fixed
  dimension, and finite numbers. Authentication, throttling, timeout, 5xx, and invalid-response
  failures become supplier-neutral safe error codes with bounded retries.
- One `knowledge_indexing` Job reuses the PostgreSQL/Redis/ARQ infrastructure. It runs rule check,
  LLM quality judgment, Embedding, and persistence without creating separate Quality or Embedding
  Jobs. A version can have only one active indexing Job.
- Administrators can start indexing, inspect rule/DeepSeek summaries and abnormal Chunks, toggle
  the final Chunk switch, inspect the non-secret active Embedding configuration and Job stage,
  publish a valid version, view the current published version, and take a document offline.
- Publication is atomic. A replacement version does not displace the old published version until
  it is ready. Publishing requires at least one enabled Chunk and, for every enabled Chunk, an
  Embedding matching the active provider, model, dimensions, and Chunk `content_hash`.

## 3. Final Chunk semantics

- `auto_indexable: boolean | null`: `null` means not yet checked; `true` or `false` is the rules
  and DeepSeek automatic recommendation.
- `enabled: boolean`: final indexing switch. On the first completed quality pass it defaults to
  `auto_indexable`; later the administrator may enable or disable it. A correction invalidates the
  version's prior ready-to-publish state and requires re-indexing.
- `quality_issues: JSONB`: normalized rule and LLM warning/error summaries.
- `extracted_metadata: JSONB`: minimal `knowledge_type`, `topics`, and `technologies` metadata.
- `quality_checked_at`, `quality_model`, and `quality_reason`: latest automatic check summary.

There is no duplicate `is_indexable` persistence field. Only `enabled=true` Chunks are embedded.
Future retrieval must additionally require an active-config Embedding with a matching content
hash, the document's current published version, and Recruiter project authorization; retrieval
itself is not implemented here.

## 4. DeepSeek schema

The external structured result contains only:

```json
{
  "chunk_id": "UUID",
  "is_indexable": true,
  "issues": [],
  "knowledge_type": "technical_decision",
  "topics": ["RAG", "LangGraph"],
  "technologies": ["FastAPI", "Redis"],
  "reason": "The content contains a concrete technical decision and its rationale."
}
```

The provider does not alter Chunk text, invent candidate experience, create authorization fields,
or persist model reasoning.

## 5. Job and version state machines

Version success path:

```text
ready_for_review -> indexing -> ready_to_publish -> published
```

Failure path:

```text
indexing -> indexing_failed
```

Job stages are `rule_check`, `llm_quality_check`, `embedding`, and `saving`. Redis carries only the
Job UUID; durable state remains in PostgreSQL. Publishing a newer version changes the old current
version to `superseded`. Taking a document offline clears `current_published_version_id` and
supersedes the former current version.

## 6. Migration and persistence

The single unapplied Phase 2.4 revision was rewritten as
`alembic/versions/c8e4f1a7b2d9_create_phase_2_4_mvp.py`; no Phase 0–2.3 migration was changed.
It:

- enables the PostgreSQL `vector` extension;
- extends the allowed version and Job states and adds the `knowledge_indexing` Job type;
- adds the minimal quality fields to `document_chunks`;
- creates `chunk_embeddings` with `provider_name`, `model_name`, `dimensions`, `content_hash`, and
  a pgvector value;
- enforces uniqueness on `(chunk_id, provider_name, model_name, dimensions)`;
- adds nullable `knowledge_documents.current_published_version_id` with a foreign key and index;
- downgrades in dependency-safe order, removes indexing-only Job history, restores legacy checks,
  and drops the vector extension last.

## 7. Active Embedding configuration

The current local Worker configuration is:

- provider name: `zhipu`;
- OpenAI-compatible base URL: `https://open.bigmodel.cn/api/paas/v4`;
- model: `embedding-3`;
- dimensions: `1024`;
- send dimensions: enabled;
- batch size: `10`;
- timeout: `30` seconds;
- maximum retries: `2`.

The implementation remains generic and contains no 智谱-specific route, service, Worker logic,
Provider subclass, or factory branch. API keys are `SecretStr` values loaded only from the ignored
local `.env`; tracked `.env.example` contains blank placeholders.

## 8. Real integration evidence

All live checks used fictional technical content and removed their database records afterward.
No secret value, Authorization header, or full private Chunk was printed or persisted in logs.

- Real 智谱 `embedding-3`: the opt-in integration test made a live request, validated a 1024-value
  vector, wrote it to PostgreSQL/pgvector, exercised publish/unpublish, and passed (`1 passed,
  1 deselected`).
- Real DeepSeek V4 Pro: one fictional batch passed strict JSON validation with thinking disabled,
  exactly one decision, and an exact current-batch Chunk ID match.
- Unified live Job: real DeepSeek judgment and real 智谱 Embedding completed through ARQ-compatible
  Worker boundaries, pgvector persistence, publication, and unpublication. The observed version
  path was `ready_for_review -> indexing -> ready_to_publish -> published -> superseded`, and the
  stored Embedding content hash matched the Chunk.
- Docker Backend and Worker were rebuilt with the local `.env`. Backend startup completed, the
  Worker registered both document-processing and knowledge-indexing functions, and final database
  cleanup found no live-test projects or orphan `chunk_embeddings`.

## 9. Verification results

The final verification was run against the completed code and local PostgreSQL/Redis services:

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed; 125 files already formatted.
- `uv run pytest -q`: passed with 459 tests passed and 2 skipped in 42.11 seconds.
- `uv run alembic upgrade head`: passed.
- `uv run alembic current`: passed at `c8e4f1a7b2d9 (head)`.
- `uv run alembic check`: passed with no new upgrade operations detected.
- Frontend `npm run lint`: passed.
- Frontend `npm run typecheck`: passed.
- Frontend `npm test -- --run`: 11 files and 63 tests passed.
- Frontend `npm run build`: passed; Vite production build completed.
- `docker compose config --quiet`: passed.
- The opt-in non-billable real PostgreSQL/pgvector publish/unpublish boundary was rerun with a
  deterministic Fake Embedding and passed (`1 passed`). No external model API was called by this
  closure revalidation.
- Docker Compose status showed Backend and Worker up, with PostgreSQL and Redis healthy; HTTP
  liveness returned `live` and readiness returned `ready`.
- `git diff --check`: passed after removing one Markdown trailing-whitespace finding.

The local `.env` introduced one initially failing Worker test because that unit test implicitly
depended on the absence of a developer key. The test now supplies explicit empty `SecretStr`
values; the focused regression test and the full suite pass without changing production startup
behavior.

## 10. Backend and frontend interfaces

Administrator-only backend interfaces added or extended by this slice:

| Method | Path | Responsibility |
| --- | --- | --- |
| `POST` | `/api/v1/admin/document-versions/{version_id}/index` | Create or recover the single active `knowledge_indexing` Job. |
| `GET` | `/api/v1/admin/jobs/{job_id}` | Return durable Job type, status, stage, progress, and safe error summary. |
| `GET` | `/api/v1/admin/document-versions/{version_id}/chunks` | Return Chunk content and latest quality/indexing summary. |
| `PATCH` | `/api/v1/admin/document-chunks/{chunk_id}` | Change the final `enabled` switch and require re-indexing. |
| `GET` | `/api/v1/admin/embedding-config` | Return only the current non-secret generic Embedding configuration. |
| `POST` | `/api/v1/admin/document-versions/{version_id}/publish` | Atomically publish a complete `ready_to_publish` version. |
| `DELETE` | `/api/v1/admin/documents/{document_id}/publication` | Clear the current published version and take the document offline. |

The React administrator interface uses the existing document detail, Job, and Chunk routes:

- `/admin/documents/:documentId` starts processing/indexing, shows versions and current publication,
  and exposes publish/offline actions;
- `/admin/jobs/:jobId` shows both document-processing and knowledge-indexing stages;
- `/admin/document-versions/:versionId/chunks` shows rule/DeepSeek summaries, issues, metadata,
  the non-secret active Embedding configuration, and the simple enabled switch.

There is no Recruiter knowledge-search, Chat, or public-agent API in this slice.

## 11. Main files added or changed

- Migration and models: `alembic/versions/c8e4f1a7b2d9_create_phase_2_4_mvp.py`,
  `app/models/document_chunk.py`, `app/models/chunk_embedding.py`,
  `app/models/knowledge_document.py`, and `app/models/document_version.py`.
- Rules and adapters: `app/quality/`, `app/infrastructure/deepseek_quality.py`, and
  `app/infrastructure/embedding.py`.
- Application flow: `app/repositories/indexing.py`, `app/services/indexing.py`,
  `app/services/indexing_worker.py`, `app/repositories/publication.py`,
  `app/services/publication.py`, `app/worker.py`, and the administrator routes/schemas.
- Administrator UI: the document detail, Chunk, Job, API, and type modules under `frontend/src/`.
- Tests: rule/schema/provider, indexing, publication, migration, PostgreSQL integration, API,
  Worker, and frontend coverage under `tests/` and `frontend/src/`.

## 12. Remaining boundaries and next checkpoint

This phase does not implement vector search, Retriever, RAG, citations, recruiter-facing Chat, or
LangGraph. It also does not add a quality dashboard, prompt/model management UI, or vendor-specific
Embedding abstractions.

Phase 2 is complete. Any next phase may begin only after explicit user confirmation and must
receive a separately confirmed scope. Until then, retrieval, RAG, Retriever, LangGraph, Chat, and
SSE remain explicitly forbidden.

## 13. Git checkpoint

This section records the pre-commit snapshot on branch `main`. At that capture, Git reported 38
modified tracked files, 43 untracked files, and no staged files. The tracked diff summary was 38
files with 1,743 insertions and 248 deletions; new untracked Phase 2.4 and final-summary files were
not counted in that diff summary. The untracked `.idea/` editor metadata is unrelated and must not
be included in the Phase 2 commit. Checkpoint preparation did not automatically stage, commit,
tag, push, or merge anything. Any later user-authorized completion commit is represented by Git
history rather than by rewriting this pre-commit evidence.

## 14. Phase 2 lifecycle closure addendum

### Objective and scope correction

The Phase 3 audit exposed a blocking Project-only assumption. Phase 3 was paused and a minimal
Phase 2 closure patch was completed. This addendum is the latest Phase 2 checkpoint fact and does
not create Phase 2.5 or begin Phase 3.

### Functionality completed

- Profile-global and Project-scoped Knowledge Documents with database-enforced nullability rules.
- Multiple Profile resumes through the existing processing, indexing, and publication pipeline.
- Exact-hash deduplication across current-published Profile documents or within one current-
  published Project scope, with stable canonical selection and one active Embedding per hash.
- Explicit disabled sources for hard blocks, exact duplicates, quality decisions, and administrator
  decisions; protected chunks are never accidentally re-enabled.
- Separate unpublish and permanent-delete semantics, safe non-current Version deletion, active-Job
  conflicts, database cascades, and post-mutation deduplication rebuilding.
- `/admin/profile-documents` plus shared document detail/version/processing/indexing/publication UI.

### Main files

- Migration/models: `e1b7c9d4a2f6_phase_2_lifecycle_patch.py`, Knowledge Document, Document Version,
  Document Chunk, and Embedding-related model changes.
- Backend: Profile document repository/service/routes, deduplication repository/service,
  lifecycle repository/service, publication integration, and application dependency wiring.
- Frontend: Profile Documents page, shared detail version deletion, API/type/router/navigation.
- Tests: lifecycle Migration/model/API/repository/service, deduplication, real PostgreSQL lifecycle,
  and React page coverage.

### Latest verification evidence

- Ruff check passed; Ruff format check reported 137 files already formatted.
- Full backend suite: 493 passed, 3 skipped in 45.15 seconds.
- Full frontend suite: 12 files and 69 tests passed; lint, typecheck, and production build passed.
- Real Alembic current: `e1b7c9d4a2f6 (head)`; check reported no new operations.
- Isolated safe downgrade cycle passed and its temporary database was removed.
- Real PostgreSQL/pgvector lifecycle integration passed (`1 passed in 2.35s`).
- Real 智谱 `embedding-3` + pgvector publication integration passed (`1 passed in 2.60s`).
- Docker Compose configuration passed; PostgreSQL and Redis were healthy.

### Remaining boundary

Retriever, RAG, LangGraph, interview APIs/pages, Chat, SSE, multi-turn persistence, hybrid search,
and reranking remain unimplemented. Phase 3 is still not started and requires explicit user
confirmation. No Commit, Tag, Push, Merge, Reset, Clean, Restore, or Rebase was performed.

### Current Git checkpoint for this addendum

- Branch: `main`.
- Staged files: 0.
- Working tree: 38 modified tracked files and 18 untracked entries at capture time.
- Tracked diff summary: 38 files changed, 1,390 insertions, 43 deletions. Untracked files are not
  included in that Git diff summary.
- The pre-existing untracked `.idea/` directory is unrelated editor metadata and was not modified.
- The pre-existing `AGENTS.md` and untracked `docs/PHASE3_PLAN.md` work was preserved and updated
  only where this request explicitly required lifecycle status and retrieval-baseline corrections.
