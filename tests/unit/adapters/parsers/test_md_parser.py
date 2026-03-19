from __future__ import annotations

import hashlib
from pathlib import Path

from repogpt.adapters.parsers.md_parser import MarkdownParser
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.utils.tree_utils import flatten_tree

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _loaded_file(filename: str) -> LoadedFile:
    path = DATA_DIR / filename
    raw = path.read_bytes()
    return LoadedFile(
        collected_file=CollectedFile(abs_path=path, relative_path=filename, language="md"),
        raw_bytes=raw,
        text=raw.decode("utf-8", errors="replace"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )


def _parse(filename: str) -> CodeNode:
    return MarkdownParser().parse(_loaded_file(filename))


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
    content = "# Demo\n```python\nprint('ok')\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(
                abs_path=fixture,
                relative_path="unclosed.md",
                language="md",
            ),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
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
    content = "# Demo\n```python\n# Not a heading\n[click](https://example.com)\n```\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(
                abs_path=fixture,
                relative_path="fenced.md",
                language="md",
            ),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    nodes = flatten_tree(root)

    assert [node["type"] for node in nodes].count("heading") == 1
    assert [node["type"] for node in nodes].count("link") == 0
    assert root.metrics["heading_count"] == 1
    assert root.metrics["link_count"] == 0


def test_markdown_tilde_fence_is_recognized_as_code_block(tmp_path: Path) -> None:
    fixture = tmp_path / "tilde.md"
    content = "# Demo\n~~~python\nprint(1)\n~~~\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(abs_path=fixture, relative_path="tilde.md", language="md"),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    nodes = flatten_tree(root)

    code_blocks = [node for node in nodes if node["type"] == "code_block"]
    assert len(code_blocks) == 1
    assert code_blocks[0]["attributes"]["fence_language"] == "python"
    assert code_blocks[0]["start_line"] == 2
    assert code_blocks[0]["end_line"] == 4


def test_markdown_tilde_fence_not_closed_by_backtick_fence(tmp_path: Path) -> None:
    fixture = tmp_path / "mixed.md"
    content = "~~~python\nprint(1)\n```\nprint(2)\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(abs_path=fixture, relative_path="mixed.md", language="md"),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    nodes = flatten_tree(root)

    code_blocks = [node for node in nodes if node["type"] == "code_block"]
    assert len(code_blocks) == 1
    assert code_blocks[0]["attributes"].get("is_unclosed") is True
    assert code_blocks[0]["end_line"] == 4


def test_markdown_fence_info_string_with_space_uses_first_token(tmp_path: Path) -> None:
    fixture = tmp_path / "info.md"
    content = "```python {.class}\ncode here\n```\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(abs_path=fixture, relative_path="info.md", language="md"),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    nodes = flatten_tree(root)

    code_blocks = [node for node in nodes if node["type"] == "code_block"]
    assert len(code_blocks) == 1
    assert code_blocks[0]["attributes"]["fence_language"] == "python"
