from hashlib import sha256
from uuid import uuid4

import pytest

from app.quality.rules import (
    ChunkRuleInput,
    RuleConfig,
    RuleIssueCode,
    RuleSeverity,
    validate_chunks,
)


def make_chunk(content: str, *, index: int = 0, content_hash: str | None = None):
    return ChunkRuleInput(
        chunk_id=uuid4(),
        chunk_index=index,
        content=content,
        content_hash=content_hash or sha256(content.encode("utf-8")).hexdigest(),
    )


def issue_codes(result) -> set[RuleIssueCode]:
    return {issue.code for issue in result.issues}


def test_empty_content_is_hard_blocked_without_external_content() -> None:
    chunk = make_chunk(" \n\t")

    result = validate_chunks([chunk])[0]

    assert result.hard_blocked is True
    assert result.redacted_content is None
    assert issue_codes(result) == {RuleIssueCode.EMPTY_CONTENT, RuleIssueCode.TOO_SHORT}
    assert all(issue.severity is RuleSeverity.HARD_BLOCK for issue in result.issues[:1])


def test_exact_duplicates_keep_first_chunk_and_block_only_later_copies() -> None:
    digest = "a" * 64
    chunks = [
        make_chunk("same content", index=3, content_hash=digest),
        make_chunk("same content", index=1, content_hash=digest),
        make_chunk("same content", index=2, content_hash=digest),
    ]

    results = validate_chunks(chunks, config=RuleConfig(min_characters=0))
    by_index = {result.chunk_index: result for result in results}

    assert by_index[1].hard_blocked is False
    assert RuleIssueCode.EXACT_DUPLICATE not in issue_codes(by_index[1])
    assert by_index[2].hard_blocked is True
    assert by_index[3].hard_blocked is True
    assert by_index[2].redacted_content is None


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (
            "-----BEGIN PRIVATE KEY-----\nfictional-test-material\n-----END PRIVATE KEY-----",
            RuleIssueCode.POSSIBLE_PRIVATE_KEY,
        ),
        ("api_key = sk-fictional1234567890abcdef", RuleIssueCode.POSSIBLE_API_KEY),
        ("Authorization: Bearer fictional-token-value-123456", RuleIssueCode.POSSIBLE_TOKEN),
        (
            "eyJmaWN0aW9uYWwiOiJ0ZXN0In0.eyJzdWIiOiJ0ZXN0In0.abcdefghijklmnop",
            RuleIssueCode.POSSIBLE_TOKEN,
        ),
        ("password = fictional-password-value", RuleIssueCode.POSSIBLE_PASSWORD),
        (
            "postgresql://fictional_user:fictional_password@db.example/test",
            RuleIssueCode.POSSIBLE_DATABASE_CREDENTIAL,
        ),
    ],
)
def test_secret_patterns_are_hard_blocked_and_never_returned_for_external_use(
    content: str,
    expected_code: RuleIssueCode,
) -> None:
    result = validate_chunks([make_chunk(content)], config=RuleConfig(min_characters=0))[0]

    assert result.hard_blocked is True
    assert result.redacted_content is None
    assert expected_code in issue_codes(result)
    assert content not in repr(result.issues)


def test_phone_and_email_are_redacted_but_remain_warnings() -> None:
    content = "联系邮箱 fictional.person@example.test，手机号 13800138000。"

    result = validate_chunks([make_chunk(content)], config=RuleConfig(min_characters=0))[0]

    assert result.hard_blocked is False
    assert result.contains_personal_contact is True
    assert issue_codes(result) == {
        RuleIssueCode.POSSIBLE_EMAIL,
        RuleIssueCode.POSSIBLE_PHONE,
    }
    assert result.redacted_content is not None
    assert "fictional.person@example.test" not in result.redacted_content
    assert "13800138000" not in result.redacted_content
    assert "[REDACTED_EMAIL]" in result.redacted_content
    assert "[REDACTED_PHONE]" in result.redacted_content
    assert content == result.original_content


def test_length_and_abnormal_character_rules_are_configurable_warnings() -> None:
    short = make_chunk("abc", index=0)
    long = make_chunk("abcdefghijk", index=1)
    abnormal = make_chunk("normal\x00\x01\x02", index=2)
    config = RuleConfig(
        min_characters=5,
        max_characters=10,
        abnormal_character_ratio=0.2,
    )

    results = validate_chunks([short, long, abnormal], config=config)

    assert issue_codes(results[0]) == {RuleIssueCode.TOO_SHORT}
    assert issue_codes(results[1]) == {RuleIssueCode.TOO_LONG}
    assert issue_codes(results[2]) == {RuleIssueCode.ABNORMAL_CHARACTERS}
    assert all(result.hard_blocked is False for result in results)
    assert all(
        issue.severity is RuleSeverity.WARNING for result in results for issue in result.issues
    )


def test_clean_chunk_passes_through_without_mutation_or_issues() -> None:
    content = "该 Chunk 解释了为什么使用 PostgreSQL 作为授权事实来源，并描述事务边界。"

    result = validate_chunks([make_chunk(content)], config=RuleConfig(min_characters=5))[0]

    assert result.issues == ()
    assert result.hard_blocked is False
    assert result.contains_personal_contact is False
    assert result.redacted_content == content
    assert result.original_content == content
