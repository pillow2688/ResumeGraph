from dataclasses import dataclass
from hashlib import sha256


class EmptyMarkdownError(Exception):
    pass


@dataclass(frozen=True)
class CleanedMarkdown:
    content: str
    content_hash: str


def clean_markdown(content: str) -> CleanedMarkdown:
    without_control_characters = content.removeprefix("\ufeff").replace("\x00", "")
    normalized_newlines = without_control_characters.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t") for line in normalized_newlines.split("\n")]

    compacted: list[str] = []
    previous_was_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_was_blank:
            continue
        compacted.append("" if is_blank else line)
        previous_was_blank = is_blank

    cleaned = "\n".join(compacted).strip()
    if not cleaned:
        raise EmptyMarkdownError
    return CleanedMarkdown(
        content=cleaned,
        content_hash=sha256(cleaned.encode("utf-8")).hexdigest(),
    )
