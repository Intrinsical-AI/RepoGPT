from __future__ import annotations

from pathlib import Path

from repogpt.adapters.parser.md_parser import MarkdownParser
from repogpt.models import CodeNode, ParserInput
from repogpt.utils.tree_utils import flatten_tree


DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _parse(filename: str) -> CodeNode:
    return MarkdownParser().parse(
        ParserInput(
            file_path=DATA_DIR / filename,
            file_info={"relative_path": filename},
        )
    )


def test_basic_markdown_builds_heading_tree() -> None:
    root = _parse("basic.md")
    assert root.type == "module"
    assert root.language == "md"
    assert root.metrics["heading_count"] == 2
    assert root.children[0].type == "heading"
    assert root.children[0].name == "Título 1"
    assert root.children[0].end_line == 5
    assert root.children[0].children[0].name == "Subtítulo"
    assert root.children[0].children[0].end_line == 5


def test_markdown_extracts_comments_tags_and_code_blocks() -> None:
    root = _parse("with_comments.md")
    nodes = flatten_tree(root)
    code_block = next(node for node in nodes if node["type"] == "code_block")

    assert root.tags == ["TODO", "FIXME"]
    assert root.comments == [
        {"text": "Este es un comentario en markdown", "line": 5},
        {"text": "TODO: Completar sección", "line": 6},
        {"text": "FIXME: Revisar formato", "line": 7},
    ]
    assert code_block["attributes"]["fence_language"] == "python"
    assert root.metrics["code_block_count"] == 1


def test_markdown_extracts_links_and_counts() -> None:
    root = _parse("edge_cases.md")
    nodes = flatten_tree(root)
    link = next(node for node in nodes if node["type"] == "link")

    assert link["attributes"]["text"] == "OpenAI"
    assert link["attributes"]["url"] == "https://openai.com"
    assert root.metrics["link_count"] == 1
    assert any("🎉" in comment["text"] for comment in root.comments)


def test_markdown_ids_are_deterministic() -> None:
    first = flatten_tree(_parse("with_comments.md"))
    second = flatten_tree(_parse("with_comments.md"))
    assert [node["id"] for node in first] == [node["id"] for node in second]


def test_markdown_unclosed_code_block_extends_to_eof(tmp_path: Path) -> None:
    fixture = tmp_path / "unclosed.md"
    fixture.write_text(
        "# Demo\n```python\nprint('ok')\n",
        encoding="utf-8",
    )

    root = MarkdownParser().parse(
        ParserInput(file_path=fixture, file_info={"relative_path": "unclosed.md"})
    )

    heading = root.children[0]
    code_block = heading.children[0]

    assert heading.end_line == 3
    assert code_block.type == "code_block"
    assert code_block.start_line == 2
    assert code_block.end_line == 3
    assert code_block.attributes["fence_language"] == "python"
    assert code_block.attributes["is_unclosed"] is True


def test_markdown_skips_headings_and_links_inside_code_fences(tmp_path: Path) -> None:
    fixture = tmp_path / "fenced.md"
    fixture.write_text(
        "# Demo\n```python\n# Not a heading\n[click](https://example.com)\n```\n",
        encoding="utf-8",
    )

    root = MarkdownParser().parse(
        ParserInput(file_path=fixture, file_info={"relative_path": "fenced.md"})
    )
    nodes = flatten_tree(root)

    assert [node["type"] for node in nodes].count("heading") == 1
    assert [node["type"] for node in nodes].count("link") == 0
    assert root.metrics["heading_count"] == 1
    assert root.metrics["link_count"] == 0
