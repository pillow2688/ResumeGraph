# Phase 2 finalization implementation plan

> **For the working AI agent:** Execute this checklist in the current uncommitted workspace because
> the facts being audited are the existing Phase 2 changes. Do not commit, tag, push, merge, reset,
> clean, restore, or rebase during this task.

**Goal:** Reconcile all Phase 2 documentation with the implemented and tested Phase 2.1–2.4
system, run the complete regression suite, and prepare an evidence-based Git handoff without
starting the next phase.

**Architecture:** Treat current code, migrations, tests, final subsection status records, and
verified live-integration evidence as the source of truth. Update only documentation and test
isolation if a reproducible regression requires it; preserve Phase 0–2.3 behavior and all security
boundaries.

**Technical stack:** Markdown, Mermaid, Python 3.12, FastAPI, SQLAlchemy/Alembic, PostgreSQL,
pgvector, Redis/ARQ, React/TypeScript, pytest, Ruff, Vitest, Vite, Docker Compose.

---

### Task 1: Audit implemented facts and obsolete scope

**Files:**

- Read: `AGENTS.md`
- Read: `README.md`
- Read: `docs/PRODUCT_SPEC.md`
- Read: `docs/RUNTIME_AGENT_HARNESS.md`
- Read: `docs/status/PHASE_2_1_STATUS.md`
- Read: `docs/status/PHASE_2_2_STATUS.md`
- Read: `docs/status/PHASE_2_3_STATUS.md`
- Read: `docs/status/PHASE_2_4_STATUS.md`
- Inspect: `app/`, `alembic/versions/`, `tests/`, and `frontend/src/`

- [ ] Confirm Phase 2.1–2.4 capabilities from code, migrations, tests, and final status records.
- [ ] Search for obsolete quality-platform, Frozen Knowledge, vendor-specific Provider, Retriever,
  RAG, LangGraph, Chat, and SSE implementation or documentation claims.
- [ ] Record any unrelated working-tree paths without changing or deleting them.

### Task 2: Rewrite the final Phase 2 roadmap

**Files:**

- Modify: `docs/PHASE2_PLAN.md`

- [ ] Replace the obsolete prospective roadmap with the final implemented Phase 2.1–2.4 route.
- [ ] Document subsection dependencies, end-to-end data flow, component responsibilities,
  cancelled designs, and the explicit post-Phase-2 stop boundary.
- [ ] Do not design or describe implementation steps for the next phase.

### Task 3: Complete Phase 2.4 learning and architecture records

**Files:**

- Modify: `docs/status/PHASE_2_4_STATUS.md`
- Create: `docs/learning/PHASE_2_4_LEARNING.md`
- Create: `docs/architecture/PHASE_2_4_ARCHITECTURE.md`

- [ ] Reconcile the status record with actual fields, Job stages, APIs, persistence, publication,
  real integration evidence, tests, limitations, and Git state.
- [ ] Explain the security-first rules/LLM/Embedding/publication design for a backend beginner.
- [ ] Add Mermaid diagrams for the system, indexing Job, responsibility split, entity relations,
  and publish/switch/unpublish state flow.

### Task 4: Create the Phase 2 summary and synchronize repository status

**Files:**

- Create: `docs/PHASE2_SUMMARY.md`
- Modify: `AGENTS.md`
- Modify: `README.md` only where a current Phase 2 statement conflicts with final facts.

- [ ] Connect Phase 2.1–2.4 into one administrator workflow and list database entities, Redis/Worker
  roles, frontend surfaces, security constraints, verification evidence, and unimplemented scope.
- [ ] Mark Phase 2 complete and the next phase not started, with links to final records.
- [ ] Keep `AGENTS.md` concise and preserve its checkpoint rules.

### Task 5: Run scope, safety, and consistency checks

**Files:**

- Inspect only: source, migrations, tests, dependencies, and documentation.

- [ ] Confirm no implemented Retriever, RAG, LangGraph, Chat, SSE, obsolete quality platform,
  Frozen Knowledge, or vendor-specific Embedding Provider remains.
- [ ] Confirm tests are collectable, dependencies are used, no temporary debug code or production
  fake fallback exists, and no unrelated Phase 0–2.3 behavior was changed by this documentation
  task.
- [ ] Check Markdown links and Mermaid blocks mechanically where repository tooling allows.

### Task 6: Execute complete regression verification

**Files:**

- Verify only; do not mutate database history or external provider state.

- [ ] Run `uv run ruff check .` and require exit code 0.
- [ ] Run `uv run ruff format --check .` and require exit code 0.
- [ ] Run `uv run pytest -q` and record exact passed/skipped counts.
- [ ] Run `uv run alembic upgrade head`, `uv run alembic current`, and `uv run alembic check`.
- [ ] Run `docker compose -f docker-compose.yml config --quiet`.
- [ ] Run frontend lint, typecheck, all tests, and production build.
- [ ] Run `git diff --check`.
- [ ] Do not claim any new external DeepSeek or Embedding call; report only the already executed
  live evidence recorded by the Phase 2.4 checkpoint.

### Task 7: Prepare the Git handoff

**Files:**

- Inspect only: Git metadata and the final working tree.

- [ ] Show branch, short status, unstaged stat, cached stat, and categorized changed files.
- [ ] Identify unrelated paths, especially editor metadata, without deleting them.
- [ ] Recommend `feat: complete phase 2 knowledge-base construction`.
- [ ] Mention the optional future annotated tag `phase-2-complete`, but do not create it.
- [ ] Stop without starting the next phase or performing any Git mutation.
