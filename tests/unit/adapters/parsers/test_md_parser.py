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
    assert root.children[0].children[0].name == "Subtítulo"


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
