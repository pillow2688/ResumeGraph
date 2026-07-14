from typing import Protocol


class HealthDependency(Protocol):
    async def check_health(self) -> None: ...

    async def close(self) -> None: ...


class DependencyUnavailableError(Exception):
    """Sanitized adapter error that never retains a raw driver error or connection URL."""

    def __init__(self, dependency: str) -> None:
        super().__init__(f"{dependency} is unavailable")
        self.dependency = dependency
