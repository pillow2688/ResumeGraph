import json
from dataclasses import dataclass, field
from uuid import UUID

from app.quality.rules import ChunkRuleResult


@dataclass(frozen=True, slots=True)
class QualityPromptChunk:
    chunk_id: UUID
    content: str = field(repr=False)
    rule_issues: tuple[str, ...]


def prepare_quality_prompt_chunks(
    rule_results: list[ChunkRuleResult],
) -> list[QualityPromptChunk]:
    prepared: list[QualityPromptChunk] = []
    for result in rule_results:
        if result.hard_blocked or result.redacted_content is None:
            continue
        prepared.append(
            QualityPromptChunk(
                chunk_id=result.chunk_id,
                content=result.redacted_content,
                rule_issues=tuple(issue.code.value for issue in result.issues),
            )
        )
    return prepared


def build_quality_messages(chunks: list[QualityPromptChunk]) -> list[dict[str, str]]:
    payload = {
        "chunks": [
            {
                "chunk_id": str(chunk.chunk_id),
                "content": chunk.content,
                "rule_issues": list(chunk.rule_issues),
            }
            for chunk in chunks
        ]
    }
    system_message = (
        "You are a constrained quality classifier for candidate-provided resume knowledge. "
        "Use only the supplied chunk text. Do not add external facts, rewrite the text, infer "
        "permissions, or output chain-of-thought. Return one result for every supplied chunk_id "
        'and no other IDs. Return JSON only as {"results":[{"chunk_id":"UUID",'
        '"is_indexable":true,"issues":[],"knowledge_type":"type",'
        '"topics":[],"technologies":[],"reason":"brief reason"}]}.'
    )
    return [
        {"role": "system", "content": system_message},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]
