from __future__ import annotations

import hashlib
from pathlib import Path

from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.utils.tree_utils import all_comments, flatten_tree

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _loaded_file(filename: str) -> LoadedFile:
    path = DATA_DIR / filename
    raw = path.read_bytes()
    return LoadedFile(
        collected_file=CollectedFile(abs_path=path, relative_path=filename, language="py"),
        raw_bytes=raw,
        text=raw.decode("utf-8", errors="replace"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )


def _parse(filename: str) -> CodeNode:
    return PythonParser().parse(_loaded_file(filename))


def test_basic_py_structure_is_stable_and_lowercase() -> None:
    root = _parse("basic.py")

    assert root.type == "module"
    assert root.path == "basic.py"
    assert root.language == "py"
    assert [child.type for child in root.children] == ["class", "function"]
    assert [child.name for child in root.children] == ["Test", "foo"]


def test_docstring_examples_capture_methods_and_docstrings() -> None:
    root = _parse("docstring_examples.py")
    nodes = flatten_tree(root)

    foo = next(node for node in nodes if node["type"] == "function" and node["name"] == "foo")
    bar = next(node for node in nodes if node["type"] == "class" and node["name"] == "Bar")
    baz = next(node for node in nodes if node["type"] == "method" and node["name"] == "baz")

    assert foo["docstring"] == "Docstring de foo"
    assert foo["attributes"]["signature"] == "foo()"
    assert bar["docstring"] == "Docstring de clase"
    assert baz["docstring"] == "Docstring de método"
    assert baz["parent_id"] == bar["id"]
    assert baz["attributes"]["params"][0]["name"] == "self"


def test_comments_are_attached_to_smallest_python_node() -> None:
    root = _parse("docstring_examples.py")
    comments = all_comments(root)
    assert any("Comentario entre docstring y código" in comment["text"] for comment in comments)
    foo = next(child for child in root.children if child.name == "foo")
    assert foo.comments == [{"text": "Comentario entre docstring y código", "line": 3}]


def test_python_import_and_signature_semantics(tmp_path: Path) -> None:
    fixture = tmp_path / "tmp_imports.py"
    content = (
        "import os as operating_system\n"
        "from pkg.sub import name as alias\n"
        "@decorator\n"
        "async def foo(a: int, /, b='x', *, c: str = 'y', **kwargs) -> str:\n"
        "    return 'ok'\n"
    )
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")
    root = PythonParser().parse(
        LoadedFile(
            collected_file=CollectedFile(
                abs_path=fixture,
                relative_path="tmp_imports.py",
                language="py",
            ),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )

    imports = [child for child in root.children if child.type == "import"]
    function = next(child for child in root.children if child.type == "function")

    assert imports[0].attributes["import_kind"] == "import"
    assert imports[0].attributes["imported_names"] == [{"name": "os", "asname": "operating_system"}]
    assert imports[1].attributes["module"] == "pkg.sub"
    assert imports[1].attributes["is_relative"] is False
    assert function.attributes["is_async"] is True
    assert function.attributes["decorators"] == ["decorator"]
    assert function.attributes["returns"] == "str"
    assert function.attributes["visibility"] == "public"
    assert (
        function.attributes["signature"]
        == "foo(a: int, /, b = 'x', *, c: str = 'y', **kwargs) -> str"
    )


def test_python_ids_are_deterministic() -> None:
    first = flatten_tree(_parse("basic.py"))
    second = flatten_tree(_parse("basic.py"))
    assert [node["id"] for node in first] == [node["id"] for node in second]


def test_python_signature_with_vararg_and_keyword_only_is_valid(tmp_path: Path) -> None:
    fixture = tmp_path / "tmp_signature.py"
    content = "def foo(*args, kw: int, **kwargs) -> None:\n    return None\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")
    root = PythonParser().parse(
        LoadedFile(
            collected_file=CollectedFile(
                abs_path=fixture,
                relative_path="tmp_signature.py",
                language="py",
            ),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )

    function = next(child for child in root.children if child.type == "function")

    assert function.attributes["signature"] == "foo(*args, kw: int, **kwargs) -> None"


def test_python_metrics_and_unicode_comments() -> None:
    root = _parse("edge_cases_comments.py")
    comments = [comment["text"] for comment in all_comments(root)]
    assert root.metrics["blank_lines"] == 4
    assert root.metrics["non_empty_lines"] > 0
    assert any("áéíóú" in text for text in comments)
    assert any("😊" in text for text in comments)
    assert any("FIXME" in text for text in comments)


def test_python_module_end_line_handles_trailing_newline(tmp_path: Path) -> None:
    fixture = tmp_path / "trailing.py"
    content = "line1\nline2\n"
    fixture.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")

    root = PythonParser().parse(
        LoadedFile(
            collected_file=CollectedFile(
                abs_path=fixture,
                relative_path="trailing.py",
                language="py",
            ),
            raw_bytes=raw,
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )

    assert root.end_line == 2


def test_associate_comments_does_not_raise_on_deep_tree() -> None:
    parser = PythonParser()
    depth = 1500
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="root.py",
        start_line=1,
        end_line=depth,
    )
    current = root
    for index in range(1, depth):
        child = CodeNode(
            id=f"node-{index}",
            type="function",
            name=f"f{index}",
            language="py",
            path="root.py",
            start_line=index,
            end_line=index,
            parent_id=current.id,
        )
        current.children.append(child)
        current = child

    parser._associate_comments(root, [{"text": "deep comment", "line": depth // 2}])

    comments = all_comments(root)
    assert any(comment["text"] == "deep comment" for comment in comments)


def test_associate_comments_attaches_to_deepest_containing_node() -> None:
    parser = PythonParser()
    inner = CodeNode(
        id="inner",
        type="function",
        name="inner",
        language="py",
        path="f.py",
        start_line=3,
        end_line=5,
    )
    outer = CodeNode(
        id="outer",
        type="class",
        name="Outer",
        language="py",
        path="f.py",
        start_line=1,
        end_line=10,
        children=[inner],
    )
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="f.py",
        start_line=1,
        end_line=10,
        children=[outer],
    )

    parser._associate_comments(root, [{"text": "inside inner", "line": 4}])
    parser._associate_comments(root, [{"text": "inside outer only", "line": 2}])
    parser._associate_comments(root, [{"text": "outside all", "line": 11}])

    assert inner.comments == [{"text": "inside inner", "line": 4}]
    assert outer.comments == [{"text": "inside outer only", "line": 2}]
    assert root.comments == [{"text": "outside all", "line": 11}]


def test_associate_comments_handles_boundary_lines_and_many_items_without_misrouting() -> None:
    parser = PythonParser()
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="root.py",
        start_line=1,
        end_line=40,
    )
    outer = CodeNode(
        id="outer",
        type="class",
        name="Outer",
        language="py",
        path="root.py",
        start_line=3,
        end_line=25,
        parent_id="root",
    )
    inner = CodeNode(
        id="inner",
        type="method",
        name="inner",
        language="py",
        path="root.py",
        start_line=8,
        end_line=18,
        parent_id="outer",
    )
    other = CodeNode(
        id="other",
        type="function",
        name="other",
        language="py",
        path="root.py",
        start_line=30,
        end_line=38,
        parent_id="root",
    )
    root.children.extend([outer, other])
    outer.children.append(inner)

    comments = [
        {"text": "before_first", "line": 1},
        {"text": "before_outer", "line": 2},
        {"text": "inside_outer", "line": 6},
        {"text": "inside_inner", "line": 9},
        {"text": "inside_other", "line": 30},
        {"text": "after_all", "line": 99},
    ]
    parser._associate_comments(root, comments)

    assert root.comments == [
        {"text": "before_first", "line": 1},
        {"text": "before_outer", "line": 2},
        {"text": "after_all", "line": 99},
    ]
    assert outer.comments == [{"text": "inside_outer", "line": 6}]
    assert inner.comments == [{"text": "inside_inner", "line": 9}]
    assert other.comments == [{"text": "inside_other", "line": 30}]


def test_associate_comments_with_many_comment_lines_stays_deterministic_and_fast() -> None:
    parser = PythonParser()
    depth = 800
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="root.py",
        start_line=1,
        end_line=depth,
    )
    current = root
    for index in range(1, depth):
        child = CodeNode(
            id=f"node-{index}",
            type="function",
            name=f"f{index}",
            language="py",
            path="root.py",
            start_line=index,
            end_line=index,
            parent_id=current.id,
        )
        current.children.append(child)
        current = child

    comments = [{"text": f"comment {index}", "line": index} for index in range(1, depth, 2)]
    parser._associate_comments(root, comments)

    seen_comments = all_comments(root)
    assert len(seen_comments) == len(comments)
    assert {comment["line"] for comment in seen_comments} == {entry["line"] for entry in comments}
