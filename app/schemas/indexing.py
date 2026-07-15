from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

ShortText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100),
]
ReasonText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500),
]


class ChunkQualityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chunk_id: UUID
    is_indexable: bool
    issues: list[ShortText] = Field(max_length=20)
    knowledge_type: ShortText
    topics: list[ShortText] = Field(max_length=20)
    technologies: list[ShortText] = Field(max_length=20)
    reason: ReasonText


class QualityBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    results: list[ChunkQualityDecision] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def reject_duplicate_chunk_ids(self) -> Self:
        ids = [item.chunk_id for item in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("Each chunk_id must appear exactly once.")
        return self


class QualityResponseValidationError(ValueError):
    """Raised when an external quality response violates the server-owned batch contract."""


def validate_quality_batch(
    raw_json: str,
    *,
    expected_chunk_ids: set[UUID],
) -> list[ChunkQualityDecision]:
    try:
        response = QualityBatchResponse.model_validate_json(raw_json)
    except (ValidationError, ValueError) as exc:
        raise QualityResponseValidationError("Invalid structured quality response.") from exc

    actual_chunk_ids = {item.chunk_id for item in response.results}
    if actual_chunk_ids != expected_chunk_ids:
        raise QualityResponseValidationError(
            "Quality response chunk IDs do not match the current server batch."
        )
    return response.results
