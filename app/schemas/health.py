from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["live"]


class DependencyStatuses(BaseModel):
    postgresql: Literal["up", "down"]
    redis: Literal["up", "down"]


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    dependencies: DependencyStatuses
