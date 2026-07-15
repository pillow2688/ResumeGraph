import re
from dataclasses import dataclass

_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class MarkdownChunkDraft:
    chunk_index: int
    heading_path: tuple[str, ...]
    content: str


@dataclass(frozen=True)
class _Section:
    heading_line: str | None
    heading_path: tuple[str, ...]
    body_lines: tuple[str, ...]


def _heading(line: str) -> tuple[int, str] | None:
    match = _ATX_HEADING.match(line)
    if match is None:
        return None
    title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
    if not title:
        return None
    return len(match.group(1)), title


def _closes_fence(line: str, *, character: str, minimum_length: int) -> bool:
    without_indent = line.lstrip(" ")
    if len(line) - len(without_indent) > 3:
        return False
    marker = without_indent.rstrip(" \t")
    return len(marker) >= minimum_length and all(item == character for item in marker)


def _split_blocks(lines: tuple[str, ...]) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    fence_character: str | None = None
    fence_length = 0

    def flush() -> None:
        if current:
            blocks.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        fence = _FENCE_START.match(line)
        if fence_character is None and fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            current.append(line)
            continue
        if fence_character is not None:
            current.append(line)
            if _closes_fence(
                line,
                character=fence_character,
                minimum_length=fence_length,
            ):
                fence_character = None
                fence_length = 0
            continue
        if not line.strip():
            flush()
        else:
            current.append(line)
    flush()
    return blocks


def _sections(content: str) -> list[_Section]:
    sections: list[_Section] = []
    heading_line: str | None = None
    heading_path: tuple[str, ...] = ()
    body_lines: list[str] = []
    heading_levels: dict[int, str] = {}
    document_title_consumed = False
    fence_character: str | None = None
    fence_length = 0

    def flush() -> None:
        nonlocal body_lines
        if heading_line is not None or any(line.strip() for line in body_lines):
            sections.append(
                _Section(
                    heading_line=heading_line,
                    heading_path=heading_path,
                    body_lines=tuple(body_lines),
                )
            )
        body_lines = []

    for line in content.strip().split("\n"):
        fence = _FENCE_START.match(line)
        if fence_character is None and fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            body_lines.append(line)
            continue
        if fence_character is not None:
            body_lines.append(line)
            if _closes_fence(
                line,
                character=fence_character,
                minimum_length=fence_length,
            ):
                fence_character = None
                fence_length = 0
            continue

        parsed_heading = _heading(line)
        if parsed_heading is None:
            body_lines.append(line)
            continue

        flush()
        level, title = parsed_heading
        heading_line = line.rstrip()
        if level == 1 and not document_title_consumed:
            document_title_consumed = True
            heading_levels.clear()
            heading_path = ()
            continue
        for existing_level in tuple(heading_levels):
            if existing_level >= level:
                del heading_levels[existing_level]
        heading_levels[level] = title
        heading_path = tuple(heading_levels[path_level] for path_level in sorted(heading_levels))
    flush()
    return sections


def _render(heading_line: str | None, blocks: list[str]) -> str:
    parts = ([heading_line] if heading_line is not None else []) + blocks
    return "\n\n".join(parts)


def split_markdown(content: str, *, max_characters: int) -> list[MarkdownChunkDraft]:
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")

    pending: list[tuple[tuple[str, ...], str]] = []
    for section in _sections(content):
        blocks = _split_blocks(section.body_lines)
        if not blocks:
            continue
        current: list[str] = []
        for block in blocks:
            candidate = _render(section.heading_line, [*current, block])
            if current and len(candidate) > max_characters:
                pending.append((section.heading_path, _render(section.heading_line, current)))
                current = [block]
            else:
                current.append(block)
        if current:
            pending.append((section.heading_path, _render(section.heading_line, current)))

    if not pending and content.strip():
        pending.append(((), content.strip()))
    return [
        MarkdownChunkDraft(
            chunk_index=index,
            heading_path=heading_path,
            content=chunk_content,
        )
        for index, (heading_path, chunk_content) in enumerate(pending)
    ]
