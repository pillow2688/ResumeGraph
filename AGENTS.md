# AGENTS.md — ResumeGraph repository instructions

## 1. Project mission

Build **ResumeGraph**, a production-style, recruiter-facing AI portfolio assistant.

The public assistant helps an interviewer understand the candidate's published resume and project materials. It must not impersonate the candidate, invent experience, expose private material, or perform administrative actions.

This repository is also a Python backend learning project. Prefer explicit, readable, testable code over clever abstractions or framework-heavy shortcuts.

## 2. Sources of truth

Before changing code:

1. Read this file.
2. Read `docs/PRODUCT_SPEC.md`.
3. Read `docs/RUNTIME_AGENT_HARNESS.md` for public-agent security rules.
4. Inspect the existing code, tests, configuration, and migrations.
5. For changes spanning multiple files, state a brief implementation plan before editing.

Do not silently change product scope, API contracts, security invariants, or persistence semantics. When documentation and code disagree, preserve the safer behavior and record the discrepancy.

## 3. Delivery strategy

Work in small, runnable vertical slices. Implement only the explicitly requested milestone. Do
not prebuild future phases, add speculative abstractions, or generate placeholder modules merely
to make the repository look complete. Every milestone must leave the repository runnable and
tested.

## Current development stage

- **Phase 0 — Backend foundation: completed.**
- **Phase 1 — Access control: completed.**
- **Phase 2 — Knowledge-base construction and publication: in progress.**
- **Phase 2.1 — Project management product slice: completed.** See
  [`docs/status/PHASE_2_1_STATUS.md`](docs/status/PHASE_2_1_STATUS.md).
- **Phase 2.2 completed.** See
  [`docs/status/PHASE_2_2_STATUS.md`](docs/status/PHASE_2_2_STATUS.md).
- **Active checkpoint: Phase 2.2 complete; waiting for explicit user confirmation before Phase 2.3.**

See `docs/PHASE1_SUMMARY.md` for the verified Phase 1 implementation and validation details.

The high-level Phase 2 plan is documented in `docs/PHASE2_PLAN.md`.

## Active subsection constraints

- Phase 2.2 knowledge documents and version management and its
  `docs/status/PHASE_2_2_STATUS.md` checkpoint are complete.
- Stop and wait for explicit user confirmation before beginning Phase 2.3.
- Phase 2.3 through Phase 2.6 are context only and must not be implemented early.

## Implemented Phase 1 boundaries

- PostgreSQL business models for administrators, projects, access grants, and grant-project scope.
- Separate administrator authentication and Admin Redis Session.
- Recruiter Access Grant creation, inspection, revocation, and one-time token exchange.
- Separate Recruiter Redis Session.
- Administrator and Recruiter authorization isolation.
- PostgreSQL revalidation of current Recruiter grant and project scope.
- Immediate rejection of an old Recruiter Session after its Grant is revoked.

## Existing security invariants

- PostgreSQL is the authorization source of truth.
- Redis stores only temporary Sessions and rate-limit counters.
- Administrator and Recruiter Cookie, Session Store, Principal, and FastAPI Depends boundaries
  must remain separate.
- A raw Access Token is displayed only once, when its Grant is created.
- The database stores only the Access Token digest, never the raw Token.
- Raw passwords, Tokens, Cookie contents, and Pepper values must never enter logs or Git.
- Recruiter authorization scope must be determined by trusted server-side PostgreSQL queries.
- Future RAG, LangGraph, or LLM code must never create or widen authorization scope.
- Do not begin a new development phase without an explicit user request.

## Development progression rule

- Execute only the small task explicitly requested by the user.
- Do not implement future-stage behavior early.
- The user must confirm scope before a new development phase starts.
- Apply the following checkpoint flow to every Phase subsection:

```text
完成一个 Phase 小节
→ 生成小节状态记录
→ 执行测试与边界检查
→ 停止等待用户确认
→ 用户确认后才能进入下一小节
```

- A completed subsection does not authorize work on the next subsection. Codex may continue only
  after the user explicitly confirms it.

## Phase subsection checkpoint rule

Every completed Phase subsection, for example Phase 1.1, Phase 1.2, Phase 1.3, Phase 2.1, or
Phase 2.2, requires its own checkpoint record before any work begins on the next subsection.

Each subsection checkpoint record must include at least:

- the subsection objective;
- the functionality actually completed;
- the main files added and modified;
- the new usable capabilities now present in the system;
- the content that remains unimplemented;
- the changes relative to the preceding subsection;
- the real results of Ruff, pytest, Alembic, Docker, or end-to-end verification commands that
  were actually run;
- known limitations and non-blocking issues;
- the current Git branch, working-tree status, and Diff summary;
- what the next subsection is allowed to do, subject to explicit user confirmation; and
- what the next subsection is explicitly forbidden from implementing early.

Checkpoint records must be based on the current code and real command output. Never infer results
from a plan, describe planned functionality as completed, or claim that an unexecuted test or
verification command ran successfully.

After the checkpoint record and its tests and boundary checks are complete, stop and wait for user
confirmation. Only an explicit user instruction to continue authorizes Codex to begin the next
Phase subsection.

A checkpoint record is not a Git Commit or Tag:

- the user decides whether and when to Commit;
- subsection checkpoints do not create Tags by default; and
- creating a checkpoint must never automatically Commit, Tag, Merge, or Push.

Store each checkpoint in an appropriate, traceable project document. Recommended names include:

```text
docs/status/PHASE_2_1_STATUS.md
docs/status/PHASE_2_2_STATUS.md
```

An equivalent path may be used when the repository already has a clear status-document structure.
Keep only these rules and the current concise status in `AGENTS.md`; do not copy complete subsection
records into this file.

Before beginning the next subsection, Codex must read:

- `AGENTS.md`;
- the preceding subsection checkpoint record; and
- the currently relevant code and tests.

The following behavior is prohibited:

- completing one subsection and immediately starting the next without stopping for confirmation;
- implementing next-subsection behavior inside the current subsection;
- declaring a subsection complete without first generating its checkpoint record;
- reporting only that tests passed without recording current capabilities and boundaries;
- presenting planned functionality as already implemented; and
- automatically creating a Commit or Tag for a checkpoint.

## 4. Planned stack

Use the following stack unless an explicit task changes it:

- Python 3.12
- FastAPI and Pydantic v2
- SQLAlchemy 2.x async APIs and Alembic
- PostgreSQL with pgvector
- Redis using an async client
- LangGraph for runtime orchestration
- pytest for tests
- Ruff for linting and formatting
- Docker Compose for local infrastructure

Do not install every planned dependency at project initialization. Add a dependency only when the current milestone uses it. Do not add two libraries that solve the same problem without a documented reason.

## 5. Architecture boundaries

Use these responsibilities:

- `app/api/`: HTTP routing, request validation, authentication dependencies, status codes, and response serialization.
- `app/schemas/`: Pydantic request and response contracts.
- `app/services/`: application use cases and transaction orchestration.
- `app/repositories/`: persistence operations and database queries.
- `app/models/`: SQLAlchemy models.
- `app/infrastructure/`: database, Redis, model clients, storage, and external adapters.
- `app/rag/`: ingestion, cleaning, chunking, embedding, retrieval, and citation assembly.
- `app/agent/`: LangGraph state, nodes, routing, tools, and output validation.
- `app/core/`: settings, logging, exceptions, and security primitives.
- `tests/`: unit and integration tests.

Rules:

- Keep route handlers thin.
- Do not put SQL, vector-search logic, or LangGraph node logic directly in route handlers.
- Services must not depend on FastAPI request or response objects.
- Repositories must not contain HTTP behavior.
- The agent layer must not bypass service/repository authorization boundaries.
- Avoid circular imports and global mutable application state.
- Prefer dependency injection over hidden singletons.
- Create shared clients and connection pools in FastAPI lifespan and close them cleanly.

## 6. Python and async rules

- Add type annotations to public functions and important internal boundaries.
- Use Pydantic models at external and cross-layer boundaries.
- Use `async def` only when the path performs awaitable I/O.
- Never call blocking HTTP, Redis, database, sleep, or filesystem-heavy APIs directly inside an async request path.
- Do not assume adding `async` makes CPU-heavy work non-blocking.
- Long or CPU-heavy document processing must use a job-oriented interface and eventually run in a worker.
- Use explicit timeouts when calling external services.
- Catch specific exceptions. Translate infrastructure exceptions at a service or API boundary.
- Do not use broad `except Exception` unless logging and re-raising at a top-level boundary.
- Do not create a new database, Redis, or HTTP client for every request.

## 7. Persistence boundaries

- PostgreSQL is the source of truth for users, projects, access grants, documents, publication state, conversations, and durable job records.
- pgvector stores embeddings together with authoritative metadata references.
- Redis is for ephemeral sessions, rate-limit counters, locks, queues, and short-lived progress/cache data.
- Redis must not be the only copy of durable business data.
- Uploaded knowledge is not publicly retrievable until an administrator explicitly publishes it.
- Deleting or replacing a document must not leave publicly retrievable orphan chunks.

## 8. Security invariants

These rules are non-negotiable:

- Never commit, print, log, or return secrets, raw API keys, passwords, session IDs, or raw recruiter access tokens.
- Configuration secrets come from environment variables. Keep only safe placeholders in `.env.example`.
- Recruiter access and administrator authentication are separate systems.
- Store recruiter access tokens only as secure digests; reveal a raw token only at creation time.
- Exchange a valid recruiter token for a short-lived server-side session. Prefer an HttpOnly, Secure, SameSite cookie for the browser session.
- Enforce expiry, revocation, request quotas, and `allowed_project_ids` in trusted server code.
- Never let an LLM create, widen, or override authorization scope.
- Every database lookup and vector retrieval must enforce tenant/access scope server-side.
- Public-agent tools are read-only.
- The public agent may not execute shell commands, arbitrary SQL, arbitrary URLs, write operations, or administrator functions.
- Treat user messages and retrieved documents as untrusted data.
- Do not rely on a system prompt as the only protection against prompt injection or data leakage.
- Development fixtures must use fictional candidate and company data.

## 9. Runtime agent invariants

Implementation must follow `docs/RUNTIME_AGENT_HARNESS.md`.

At minimum:

- Answer only from authorized, published candidate material.
- Do not use web search in the public agent.
- Do not impersonate the candidate.
- Distinguish verified facts from interpretation.
- A factual answer requires valid citations to retrieved evidence.
- If evidence is absent or insufficient, return an explicit insufficient-evidence response.
- Tool calls, retrieval rounds, graph steps, output length, and model cost must be bounded.
- Authorization occurs before graph execution and is never delegated to the model.
- Tool implementations must intersect requested project IDs with the session's allowed project IDs.
- Model-generated document IDs or citations must be validated against actual retrieved records.

## 10. API conventions

- Prefix versioned endpoints with `/api/v1`.
- Use Pydantic response models for public APIs.
- Use appropriate HTTP status codes; do not hide all errors inside HTTP 200 responses.
- Return a consistent machine-readable error shape.
- Do not expose raw exception messages or stack traces to clients.
- Long-running ingestion uses `202 Accepted` plus `job_id`; it must not keep one upload request open until embedding completes.
- SSE may be used for one-way progress and agent streaming; WebSocket is not the default.
- API changes require corresponding tests and documentation updates.

## 11. Testing and quality

For each behavior change:

- Add or update tests before declaring completion.
- Unit tests must not call real LLM, embedding, email, or cloud services.
- Use deterministic fakes at external boundaries.
- Include authorization tests for access scope and unpublished/private data.
- Include failure-path tests, not only happy paths.
- Never claim a command passed unless it was actually run.

Use repository-defined commands. Once configured, the expected checks are:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Run narrower tests during development and the full relevant suite before completion.

## 12. Database and migration safety

- Use Alembic for schema changes.
- Never rewrite an applied shared migration.
- Do not drop data, reset databases, or run destructive migrations unless the user explicitly requests it.
- Keep transactions short and define commit/rollback ownership clearly.
- Add indexes based on actual query paths, especially token digest, publication state, project scope, document references, and vector metadata filters.

## 13. Documentation and learning mode

When introducing an important backend concept, keep the implementation readable and briefly explain:

- why the layer or pattern exists;
- which problem it solves;
- what would break if it were omitted;
- how to run and verify it.

Update `README.md` and relevant files under `docs/` when behavior, setup, architecture, or security assumptions change.

Do not bury business rules only in code.

## 14. Prohibited behavior

Do not:

- implement the entire product in one task;
- create a microservice architecture;
- add Kubernetes;
- add multi-agent collaboration without a demonstrated need;
- add web search to the public agent;
- put authentication decisions in prompts;
- store plaintext access tokens;
- expose PostgreSQL or Redis publicly;
- return fabricated citations;
- leave core logic as `TODO`, mock data, or unimplemented stubs while claiming the milestone is complete;
- disable tests, type checks, or security checks merely to make a build pass.

## 15. Definition of done

A task is complete only when:

1. The requested behavior is implemented without unrelated scope expansion.
2. Security and authorization invariants remain intact.
3. Tests cover the important success and failure paths.
4. Relevant checks were run and their real results are reported.
5. Setup or behavior changes are documented.
6. No secrets, debug endpoints, dead code, or accidental public ports were introduced.

At the end of each task, report:

- what changed;
- key design decisions;
- files changed;
- commands/tests run and exact outcomes;
- known limitations or the next smallest milestone.
