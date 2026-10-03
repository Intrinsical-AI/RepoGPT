from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from repogpt.adapters.fs.loader import DefaultLoader
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
        text=raw.decode("utf-8", errors="replace"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )


def _parse(filename: str) -> CodeNode:
    return MarkdownParser().parse(_loaded_file(filename))


def _parse_text(tmp_path: Path, content: str) -> CodeNode:
    raw = content.encode("utf-8")
    return MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(tmp_path / "sample.md", "sample.md", "md"),
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
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


def test_bom_first_heading_is_emitted_after_loading(tmp_path: Path) -> None:
    path = tmp_path / "bom.md"
    path.write_bytes(b"\xef\xbb\xbf# First\n")
    loaded = DefaultLoader().load(CollectedFile(path, "bom.md", "md"))
    root = MarkdownParser().parse(loaded)
    assert [(node.name, node.start_column) for node in root.children] == [("First", 0)]


@pytest.mark.parametrize(
    "source,title,column",
    [
        ("   # Indented\n", "Indented", 3),
        ("- # InList\n", "InList", 2),
        ("- \t# WithTab\n", "WithTab", 3),
        ("#\n", "", 0),
        ("## Closed ##\n", "Closed", 0),
    ],
)
def test_commonmark_atx_headings_use_original_columns(
    tmp_path: Path, source: str, title: str, column: int
) -> None:
    root = _parse_text(tmp_path, source)
    headings = [node for node in flatten_tree(root) if node["type"] == "heading"]
    assert [(node["name"], node["start_column"]) for node in headings] == [(title, column)]


def test_links_ignore_inline_code_and_images_but_keep_escaped_image_marker(
    tmp_path: Path,
) -> None:
    source = r"`[code](wrong)` ![image](img.png) [real](dest) \![escaped](url)" + "\n"
    root = _parse_text(tmp_path, source)
    links = [node for node in flatten_tree(root) if node["type"] == "link"]
    assert [(node["name"], node["attributes"]["url"]) for node in links] == [
        ("real", "dest"),
        ("escaped", "url"),
    ]
    assert [node["start_column"] for node in links] == [
        source.index("[real]"),
        source.index("[escaped]"),
    ]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("`\n[hidden](wrong)\n` [visible](right)\n", ["visible"]),
        ("``\n[hidden](wrong)\n` not a closer\n`` [visible](right)\n", ["visible"]),
        ("` unclosed\n[visible](right)\n\n` separate paragraph\n", ["visible"]),
        ("` unclosed\n```text\n[hidden](code)\n```\n[visible](right)\n", ["visible"]),
        ("- ` unclosed\n- [visible](right) `\n", ["visible"]),
    ],
)
def test_multiline_inline_code_spans_preserve_link_boundaries(
    tmp_path: Path, source: str, expected: list[str]
) -> None:
    root = _parse_text(tmp_path, source)
    links = [node for node in flatten_tree(root) if node["type"] == "link"]
    assert [node["name"] for node in links] == expected
    for node in links:
        original_line = source.splitlines()[node["start_line"] - 1]
        assert original_line[node["start_column"]] == "["


def test_markdown_comments_and_tags_ignore_fenced_code_and_substrings(tmp_path: Path) -> None:
    source = "<!-- mastodon -->\n```html\n<!-- TODO: fake -->\n```\n<!-- FIXME: real -->\n"
    root = _parse_text(tmp_path, source)
    assert root.comments == [
        {"text": "mastodon", "line": 1},
        {"text": "FIXME: real", "line": 5},
    ]
    assert root.tags == ["FIXME"]


def test_markdown_comments_inside_multiline_inline_code_are_ignored(tmp_path: Path) -> None:
    root = _parse_text(tmp_path, "`\n<!-- TODO: code -->\n`\n<!-- FIXME: prose -->\n")
    assert root.comments == [{"text": "FIXME: prose", "line": 4}]
    assert root.tags == ["FIXME"]


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
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    nodes = flatten_tree(root)

    code_blocks = [node for node in nodes if node["type"] == "code_block"]
    assert len(code_blocks) == 1
    assert code_blocks[0]["attributes"]["fence_language"] == "python"


@pytest.mark.parametrize(
    "content,expected",
    [
        ("    # literal\n    [hidden](code)\n[visible](prose)\n", ["visible"]),
        ("\t[hidden](code)\n\n\t[also hidden](code)\n[visible](prose)", ["visible"]),
        ("# Heading\n    [hidden](code)\n\n[visible](prose)", ["visible"]),
        ("```\ncode\n```\n    [hidden](code)\n", []),
        ("Paragraph\n    [visible](prose)\n\n    [hidden](code)", ["visible"]),
        ("Paragraph\n\t[visible](prose)", ["visible"]),
        ("```not`a-fence\n    [visible](prose)", ["visible"]),
        ("Paragraph\n2. still prose\n\n    [hidden](code)", []),
        ("-\n\n     [visible](prose)\n\n      [hidden](code)", ["visible"]),
        ("* * *\n    [hidden](code)\n[visible](prose)", ["visible"]),
        ("- Item\n\n    [visible](prose)\n\n      [hidden](code)", ["visible"]),
        ("10. Item\n\n    [visible](prose)\n\n        [hidden](code)", ["visible"]),
        ("- Item\n  - Nested\n\n      [visible](prose)\n\n        [hidden](code)", ["visible"]),
        ("- Item\n\n\t[visible](prose)\n\n\t\t[hidden](code)", ["visible"]),
        ("- Item\nlazy continuation\n\n    [visible](prose)", ["visible"]),
        ("- Item\n\nOutside\n\n    [hidden](code)\n[visible](prose)", ["visible"]),
        ("-     [hidden](code)\n\n  [visible](prose)", ["visible"]),
        ("    ```\n    [hidden](code)\n    ```\n[visible](prose)", ["visible"]),
        ("- # Heading\n      [hidden](code)\n\n  [visible](prose)", ["visible"]),
        ("- Item\n\n  # Heading\n      [hidden](code)", []),
        ("- - # Heading\n        [hidden](code)", []),
        ("- ```\n  [hidden](code)\n  ```\n[visible](prose)", ["visible"]),
        ("- Item\n  - ~~~\n    [hidden](code)\n    ~~~\n[visible](prose)", ["visible"]),
        ("- ```\n  [hidden](code)\n\n[visible](prose)", ["visible"]),
        ("- ```\n  [hidden](code)\n- [visible](prose)", ["visible"]),
        ("Paragraph\n    # literal\n    [visible](prose)", ["visible"]),
        ("- #\n      [hidden](code)", []),
        ("- * * *\n      [hidden](code)\n\n  [visible](prose)", ["visible"]),
    ],
)
def test_markdown_links_respect_indented_code_and_prose(
    tmp_path: Path, content: str, expected: list[str]
) -> None:
    raw = content.encode()
    root = MarkdownParser().parse(
        LoadedFile(
            collected_file=CollectedFile(tmp_path / "sample.md", "sample.md", "md"),
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )
    links = [node for node in flatten_tree(root) if node["type"] == "link"]
    assert [node["name"] for node in links] == expected
    assert root.metrics["link_count"] == len(expected)
    for node in links:
        line = content.splitlines()[node["start_line"] - 1]
        assert line[node["attributes"]["start_column"]] == "["


@pytest.mark.parametrize(
    "content,span,unclosed",
    [
        ("- ```py\n  [hidden](code)\n  ```\n# After\n", (1, 3), False),
        ("- Item\n  - ~~~py\n    [hidden](code)\n    ~~~\n# After\n", (2, 4), False),
        ("- ```py\n  [hidden](code)\n# After\n", (1, 2), True),
    ],
)
def test_list_fences_preserve_spans_and_stop_at_container_boundary(
    tmp_path: Path,
    content: str,
    span: tuple[int, int],
    unclosed: bool,
) -> None:
    root = MarkdownParser().parse(
        LoadedFile(
            CollectedFile(tmp_path / "sample.md", "sample.md", "md"),
            content,
            FileDigest(len(content), hashlib.sha256(content.encode()).hexdigest()),
        )
    )
    nodes = flatten_tree(root)
    blocks = [node for node in nodes if node["type"] == "code_block"]
    assert len(blocks) == root.metrics["code_block_count"] == 1
    assert (blocks[0]["start_line"], blocks[0]["end_line"]) == span
    assert blocks[0]["attributes"]["fence_language"] == "py"
    assert bool(blocks[0]["attributes"].get("is_unclosed")) is unclosed
    assert [node["name"] for node in nodes if node["type"] == "heading"] == ["After"]
