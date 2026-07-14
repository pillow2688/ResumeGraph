# First Codex task — Phase 0 only

Read `AGENTS.md`, `docs/PRODUCT_SPEC.md`, and `docs/RUNTIME_AGENT_HARNESS.md` before editing.

Implement only **Phase 0: backend foundation**. Do not implement recruiter authentication, administrator authentication, LangGraph, RAG, document upload, frontend, or LLM calls yet.

## Required outcome

Create a small, production-shaped FastAPI backend that demonstrates:

- Python 3.12 project configuration using `pyproject.toml`;
- FastAPI application factory or clear app construction;
- typed settings loaded from environment variables;
- FastAPI lifespan management;
- reusable async PostgreSQL and Redis connections;
- local PostgreSQL/pgvector and Redis through Docker Compose;
- liveness and readiness endpoints;
- consistent error responses;
- basic application logging;
- tests;
- setup documentation.

## Endpoints

Implement:

```text
GET /api/v1/health/live
GET /api/v1/health/ready
```

Expected semantics:

- `live` confirms that the FastAPI process is running and must not depend on PostgreSQL or Redis.
- `ready` checks PostgreSQL and Redis with explicit short timeouts.
- `ready` returns success only when both dependencies are available.
- Dependency errors must be sanitized; do not return credentials, DSNs, stack traces, or raw driver errors.

Use appropriate response models and HTTP status codes.

## Infrastructure constraints

- PostgreSQL and Redis must be reachable by the backend container but must not publish public production ports.
- Development Compose may bind them to localhost only when necessary.
- Provide `.env.example` with safe placeholders.
- Do not commit a real `.env`.
- Do not create clients per request.
- Do not call blocking database or Redis clients from async endpoints.
- Add a simple Alembic setup, but do not create product tables in this phase.
- Do not add Celery, LangGraph, LangChain, pgvector Python integration, or an LLM SDK yet unless it is strictly needed for the health foundation.

## Suggested repository shape

Use the minimum necessary subset:

```text
app/
  main.py
  api/
    routes/
      health.py
  core/
    config.py
    exceptions.py
    logging.py
  infrastructure/
    database.py
    redis.py
  schemas/
    health.py
tests/
alembic/
docker-compose.yml
Dockerfile
pyproject.toml
.env.example
README.md
```

Do not generate empty future directories.

## Testing

Add tests for:

- liveness success;
- readiness success using dependency fakes/mocks;
- readiness failure when PostgreSQL is unavailable;
- readiness failure when Redis is unavailable;
- sanitized error payloads.

Unit tests must not require a real LLM or external internet access. Keep integration commands documented separately if real containers are needed.

Run the relevant formatter/linter and tests. Fix failures rather than disabling checks.

## Learning-oriented implementation

Keep the code explicit. In the final summary, explain briefly:

- why `live` and `ready` are different;
- why shared clients belong in lifespan;
- where `async/await` matters in these health checks;
- why Redis and PostgreSQL are not created per request.

## Completion report

Report:

1. files created or changed;
2. architecture choices;
3. commands actually run;
4. exact test/lint outcomes;
5. how to start the services;
6. any real limitation that remains.

Do not continue to Phase 1.
