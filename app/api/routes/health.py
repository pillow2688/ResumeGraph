import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Request

from app.core.exceptions import ServiceNotReadyError
from app.infrastructure.health import DependencyUnavailableError, HealthDependency
from app.schemas.error import ErrorResponse
from app.schemas.health import DependencyStatuses, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/api/v1/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Confirm that the API process can serve requests without checking dependencies."""
    return LivenessResponse(status="live")


async def _dependency_status(
    name: str,
    dependency: HealthDependency,
    timeout_seconds: float,
) -> Literal["up", "down"]:
    try:
        await asyncio.wait_for(dependency.check_health(), timeout=timeout_seconds)
    except (DependencyUnavailableError, TimeoutError) as error:
        logger.warning(
            "Dependency readiness check failed",
            extra={"dependency": name, "error_type": type(error).__name__},
        )
        return "down"
    return "up"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        503: {
            "description": "A required dependency is unavailable",
            "model": ErrorResponse,
        }
    },
)
async def readiness(request: Request) -> ReadinessResponse:
    """Check PostgreSQL and Redis concurrently within a short configured timeout."""
    timeout_seconds = request.app.state.settings.readiness_timeout_seconds
    postgresql_status, redis_status = await asyncio.gather(
        _dependency_status("postgresql", request.app.state.database, timeout_seconds),
        _dependency_status("redis", request.app.state.redis, timeout_seconds),
    )
    dependencies = DependencyStatuses(
        postgresql=postgresql_status,
        redis=redis_status,
    )
    if postgresql_status != "up" or redis_status != "up":
        raise ServiceNotReadyError(
            details={"dependencies": dependencies.model_dump()},
        )
    return ReadinessResponse(status="ready", dependencies=dependencies)
