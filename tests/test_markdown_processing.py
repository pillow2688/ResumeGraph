from hashlib import sha256

import pytest

from app.ingestion.chunking import split_markdown
from app.ingestion.cleaning import EmptyMarkdownError, clean_markdown


def test_clean_markdown_applies_all_deterministic_rules_and_hashes_result() -> None:
    raw = "\ufeff  # ResumeGraph  \r\nLine with spaces  \r\n\x00\r\n\r\n \t\r\nNext\t \r\n"

    cleaned = clean_markdown(raw)

    assert cleaned.content == "# ResumeGraph\nLine with spaces\n\nNext"
    assert cleaned.content_hash == sha256(cleaned.content.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("raw", ["", " \r\n\t", "\ufeff\x00\r\n"])
def test_clean_markdown_rejects_content_that_is_empty_after_cleaning(raw: str) -> None:
    with pytest.raises(EmptyMarkdownError):
        clean_markdown(raw)


def test_markdown_chunking_uses_heading_hierarchy_and_omits_document_title() -> None:
    markdown = """# ResumeGraph

项目总览。

## 技术架构

架构说明。

### LangGraph

第一段。

第二段。
"""

    chunks = split_markdown(markdown, max_characters=2_000)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.heading_path for chunk in chunks] == [
        (),
        ("技术架构",),
        ("技术架构", "LangGraph"),
    ]
    assert chunks[0].content == "# ResumeGraph\n\n项目总览。"
    assert chunks[2].content == "### LangGraph\n\n第一段。\n\n第二段。"


def test_long_sections_split_only_at_paragraph_boundaries() -> None:
    markdown = "## Section\n\nAAAAAAAAAA\n\nBBBBBBBBBB\n\nCCCCCCCCCC"

    chunks = split_markdown(markdown, max_characters=30)

    assert [chunk.content for chunk in chunks] == [
        "## Section\n\nAAAAAAAAAA",
        "## Section\n\nBBBBBBBBBB",
        "## Section\n\nCCCCCCCCCC",
    ]
    assert [chunk.heading_path for chunk in chunks] == [
        ("Section",),
        ("Section",),
        ("Section",),
    ]


def test_single_overlong_paragraph_is_preserved_without_character_hard_cut() -> None:
    paragraph = "x" * 80

    chunks = split_markdown(f"## Section\n\n{paragraph}", max_characters=20)

    assert len(chunks) == 1
    assert chunks[0].content == f"## Section\n\n{paragraph}"


def test_headings_inside_fenced_code_do_not_change_heading_path() -> None:
    markdown = """# Doc

## Real section

```markdown
# not a heading
## also not a heading
```

After the fence.
"""

    chunks = split_markdown(markdown, max_characters=2_000)

    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Real section",)
    assert "# not a heading" in chunks[0].content
    assert "## also not a heading" in chunks[0].content


def test_longer_closing_fence_ends_code_before_the_next_heading() -> None:
    markdown = """# Doc

## Code

```markdown
## not a heading
````

## Real next section

After the fence.
"""

    chunks = split_markdown(markdown, max_characters=2_000)

    assert [chunk.heading_path for chunk in chunks] == [
        ("Code",),
        ("Real next section",),
    ]
    assert chunks[1].content == "## Real next section\n\nAfter the fence."


def test_chunk_order_and_content_are_stable_across_runs() -> None:
    markdown = "# Doc\n\nIntro\n\n## A\n\nOne\n\n## B\n\nTwo"

    first = split_markdown(markdown, max_characters=25)
    second = split_markdown(markdown, max_characters=25)

    assert first == second
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
