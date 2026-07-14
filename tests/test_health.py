from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.infrastructure.health import DependencyUnavailableError
from app.main import create_app


@dataclass
class FakeDependency:
    error: Exception | None = None
    check_count: int = 0
    closed: bool = False

    async def check_health(self) -> None:
        self.check_count += 1
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+asyncpg://resumegraph:local-only@postgres/resumegraph",
        redis_url="redis://redis:6379/0",
        readiness_timeout_seconds=0.1,
    )


def make_client(
    settings: Settings,
    *,
    database: FakeDependency | None = None,
    redis: FakeDependency | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            settings=settings,
            database=database or FakeDependency(),
            redis=redis or FakeDependency(),
        )
    )


def test_liveness_succeeds_without_checking_dependencies(settings: Settings) -> None:
    database = FakeDependency(error=AssertionError("liveness must not check PostgreSQL"))
    redis = FakeDependency(error=AssertionError("liveness must not check Redis"))

    with make_client(settings, database=database, redis=redis) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}
    assert database.check_count == 0
    assert redis.check_count == 0


def test_unknown_route_uses_consistent_error_response(settings: Settings) -> None:
    with make_client(settings) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Resource not found."}}


def test_readiness_documents_its_success_and_error_models(settings: Settings) -> None:
    with make_client(settings) as client:
        response = client.get("/openapi.json")

    responses = response.json()["paths"]["/api/v1/health/ready"]["get"]["responses"]
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReadinessResponse"
    }
    assert responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_readiness_succeeds_when_both_dependencies_are_available(settings: Settings) -> None:
    database = FakeDependency()
    redis = FakeDependency()

    with make_client(settings, database=database, redis=redis) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgresql": "up", "redis": "up"},
    }
    assert database.check_count == 1
    assert redis.check_count == 1
    assert database.closed is True
    assert redis.closed is True


@pytest.mark.parametrize(
    ("failed_dependency", "expected_dependencies"),
    [
        ("postgresql", {"postgresql": "down", "redis": "up"}),
        ("redis", {"postgresql": "up", "redis": "down"}),
    ],
)
def test_readiness_returns_sanitized_error_when_a_dependency_is_unavailable(
    settings: Settings,
    failed_dependency: str,
    expected_dependencies: dict[str, str],
) -> None:
    secret = "postgresql+asyncpg://admin:do-not-leak@database/resumegraph"
    database = FakeDependency()
    redis = FakeDependency()
    dependency_error = DependencyUnavailableError(failed_dependency)
    dependency_error.__cause__ = RuntimeError(secret)
    failing_fake = FakeDependency(error=dependency_error)
    if failed_dependency == "postgresql":
        database = failing_fake
    else:
        redis = failing_fake

    with make_client(settings, database=database, redis=redis) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_not_ready",
            "message": "Service dependencies are unavailable.",
            "details": {"dependencies": expected_dependencies},
        }
    }
    assert secret not in response.text
    assert "DependencyUnavailableError" not in response.text
