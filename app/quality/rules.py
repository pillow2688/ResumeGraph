import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class RuleSeverity(StrEnum):
    HARD_BLOCK = "hard_block"
    WARNING = "warning"


class RuleIssueCode(StrEnum):
    EMPTY_CONTENT = "empty_content"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    ABNORMAL_CHARACTERS = "abnormal_characters"
    EXACT_DUPLICATE = "exact_duplicate"
    POSSIBLE_PRIVATE_KEY = "possible_private_key"
    POSSIBLE_API_KEY = "possible_api_key"
    POSSIBLE_TOKEN = "possible_token"
    POSSIBLE_PASSWORD = "possible_password"
    POSSIBLE_DATABASE_CREDENTIAL = "possible_database_credential"
    POSSIBLE_PHONE = "possible_phone"
    POSSIBLE_EMAIL = "possible_email"


HARD_SECRET_CODES = frozenset(
    {
        RuleIssueCode.POSSIBLE_PRIVATE_KEY,
        RuleIssueCode.POSSIBLE_API_KEY,
        RuleIssueCode.POSSIBLE_TOKEN,
        RuleIssueCode.POSSIBLE_PASSWORD,
        RuleIssueCode.POSSIBLE_DATABASE_CREDENTIAL,
    }
)
PERSONAL_CONTACT_CODES = frozenset(
    {
        RuleIssueCode.POSSIBLE_PHONE,
        RuleIssueCode.POSSIBLE_EMAIL,
    }
)


@dataclass(frozen=True, slots=True)
class RuleConfig:
    min_characters: int = 80
    max_characters: int = 6_000
    abnormal_character_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.min_characters < 0:
            raise ValueError("Minimum characters cannot be negative.")
        if self.max_characters <= self.min_characters:
            raise ValueError("Maximum characters must exceed minimum characters.")
        if not 0 < self.abnormal_character_ratio <= 1:
            raise ValueError("Abnormal character ratio must be within (0, 1].")


@dataclass(frozen=True, slots=True)
class ChunkRuleInput:
    chunk_id: UUID
    chunk_index: int
    content: str = field(repr=False)
    content_hash: str


@dataclass(frozen=True, slots=True)
class RuleIssue:
    code: RuleIssueCode
    severity: RuleSeverity

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "severity": self.severity.value}


@dataclass(frozen=True, slots=True)
class ChunkRuleResult:
    chunk_id: UUID
    chunk_index: int
    original_content: str = field(repr=False)
    content_hash: str
    issues: tuple[RuleIssue, ...]
    hard_blocked: bool
    contains_personal_contact: bool
    redacted_content: str | None = field(repr=False)


_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_API_KEY_PATTERN = re.compile(
    r"(?:\b(?:api[_-]?key)\s*[:=]\s*['\"]?|\b)(?:sk|ak)-[A-Za-z0-9_-]{16,}",
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)
_JWT_PATTERN = re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_TOKEN_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:access[_-]?token|auth[_-]?token|token)\s*[:=]\s*['\"]?"
    r"[A-Za-z0-9._~+/=-]{12,}",
    re.IGNORECASE,
)
_PASSWORD_PATTERN = re.compile(
    r"\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    re.IGNORECASE,
)
_DATABASE_CREDENTIAL_PATTERN = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)://"
    r"[^\s:/@]+:[^\s@]+@[^\s]+",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@"
    r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"
)

_SECRET_PATTERNS: tuple[tuple[RuleIssueCode, tuple[re.Pattern[str], ...]], ...] = (
    (RuleIssueCode.POSSIBLE_PRIVATE_KEY, (_PRIVATE_KEY_PATTERN,)),
    (RuleIssueCode.POSSIBLE_API_KEY, (_API_KEY_PATTERN,)),
    (
        RuleIssueCode.POSSIBLE_TOKEN,
        (_BEARER_PATTERN, _JWT_PATTERN, _TOKEN_ASSIGNMENT_PATTERN),
    ),
    (RuleIssueCode.POSSIBLE_PASSWORD, (_PASSWORD_PATTERN,)),
    (RuleIssueCode.POSSIBLE_DATABASE_CREDENTIAL, (_DATABASE_CREDENTIAL_PATTERN,)),
)


def _has_abnormal_characters(content: str, *, threshold: float) -> bool:
    if not content:
        return False
    abnormal = sum(
        1
        for character in content
        if character not in "\n\r\t" and unicodedata.category(character).startswith("C")
    )
    return abnormal / len(content) > threshold


def _redact_personal_contact(content: str) -> str:
    redacted = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", content)
    return _PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)


def validate_chunks(
    chunks: list[ChunkRuleInput],
    *,
    config: RuleConfig | None = None,
) -> list[ChunkRuleResult]:
    active_config = config or RuleConfig()
    first_index_by_hash: dict[str, int] = {}
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        first_index_by_hash.setdefault(chunk.content_hash, chunk.chunk_index)

    results: list[ChunkRuleResult] = []
    for chunk in chunks:
        issues: list[RuleIssue] = []
        stripped_length = len(chunk.content.strip())
        if stripped_length == 0:
            issues.append(RuleIssue(RuleIssueCode.EMPTY_CONTENT, RuleSeverity.HARD_BLOCK))
        if stripped_length < active_config.min_characters:
            issues.append(RuleIssue(RuleIssueCode.TOO_SHORT, RuleSeverity.WARNING))
        if len(chunk.content) > active_config.max_characters:
            issues.append(RuleIssue(RuleIssueCode.TOO_LONG, RuleSeverity.WARNING))
        if _has_abnormal_characters(
            chunk.content,
            threshold=active_config.abnormal_character_ratio,
        ):
            issues.append(RuleIssue(RuleIssueCode.ABNORMAL_CHARACTERS, RuleSeverity.WARNING))
        if first_index_by_hash[chunk.content_hash] != chunk.chunk_index:
            issues.append(RuleIssue(RuleIssueCode.EXACT_DUPLICATE, RuleSeverity.HARD_BLOCK))

        for code, patterns in _SECRET_PATTERNS:
            if any(pattern.search(chunk.content) is not None for pattern in patterns):
                issues.append(RuleIssue(code, RuleSeverity.HARD_BLOCK))

        if _PHONE_PATTERN.search(chunk.content) is not None:
            issues.append(RuleIssue(RuleIssueCode.POSSIBLE_PHONE, RuleSeverity.WARNING))
        if _EMAIL_PATTERN.search(chunk.content) is not None:
            issues.append(RuleIssue(RuleIssueCode.POSSIBLE_EMAIL, RuleSeverity.WARNING))

        hard_blocked = any(issue.severity is RuleSeverity.HARD_BLOCK for issue in issues)
        contains_personal_contact = any(issue.code in PERSONAL_CONTACT_CODES for issue in issues)
        results.append(
            ChunkRuleResult(
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                original_content=chunk.content,
                content_hash=chunk.content_hash,
                issues=tuple(issues),
                hard_blocked=hard_blocked,
                contains_personal_contact=contains_personal_contact,
                redacted_content=(
                    None if hard_blocked else _redact_personal_contact(chunk.content)
                ),
            )
        )
    return results
