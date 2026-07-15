import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas.indexing import (
    ChunkQualityDecision,
    QualityBatchResponse,
    QualityResponseValidationError,
    validate_quality_batch,
)


def decision_payload(chunk_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "chunk_id": str(chunk_id),
        "is_indexable": True,
        "issues": [],
        "knowledge_type": "technical_decision",
        "topics": ["RAG", "LangGraph"],
        "technologies": ["FastAPI", "Redis"],
        "reason": "内容包含明确的技术方案和选型依据",
    }
    payload.update(overrides)
    return payload


def test_minimal_quality_json_is_strictly_validated() -> None:
    chunk_id = uuid4()
    raw = json.dumps({"results": [decision_payload(chunk_id)]})

    result = QualityBatchResponse.model_validate_json(raw)

    assert result.results == [
        ChunkQualityDecision(
            chunk_id=chunk_id,
            is_indexable=True,
            issues=[],
            knowledge_type="technical_decision",
            topics=["RAG", "LangGraph"],
            technologies=["FastAPI", "Redis"],
            reason="内容包含明确的技术方案和选型依据",
        )
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("reason"),
        lambda payload: payload.update({"quality_score": 0.9}),
        lambda payload: payload.update({"is_indexable": "true"}),
        lambda payload: payload.update({"issues": [1]}),
        lambda payload: payload.update({"knowledge_type": ""}),
        lambda payload: payload.update({"topics": ["x"] * 21}),
        lambda payload: payload.update({"reason": "x" * 501}),
    ],
)
def test_missing_invalid_or_overdesigned_fields_are_rejected(mutation) -> None:
    payload = decision_payload(uuid4())
    mutation(payload)

    with pytest.raises(ValidationError):
        QualityBatchResponse.model_validate_json(json.dumps({"results": [payload]}))


def test_current_batch_chunk_ids_must_match_exactly_once() -> None:
    first_id = uuid4()
    second_id = uuid4()
    expected = {first_id, second_id}

    accepted = validate_quality_batch(
        json.dumps({"results": [decision_payload(first_id), decision_payload(second_id)]}),
        expected_chunk_ids=expected,
    )
    assert {item.chunk_id for item in accepted} == expected

    invalid_batches = [
        {"results": [decision_payload(first_id)]},
        {
            "results": [
                decision_payload(first_id),
                decision_payload(second_id),
                decision_payload(uuid4()),
            ]
        },
        {
            "results": [
                decision_payload(first_id),
                decision_payload(first_id),
            ]
        },
    ]
    for payload in invalid_batches:
        with pytest.raises(QualityResponseValidationError):
            validate_quality_batch(
                json.dumps(payload),
                expected_chunk_ids=expected,
            )


@pytest.mark.parametrize("raw", ["", "not-json", "{}", '{"results": []}'])
def test_empty_or_malformed_batch_is_rejected(raw: str) -> None:
    with pytest.raises(QualityResponseValidationError):
        validate_quality_batch(raw, expected_chunk_ids={uuid4()})
