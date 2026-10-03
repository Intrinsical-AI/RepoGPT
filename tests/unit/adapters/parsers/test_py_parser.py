from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.utils.tree_utils import flatten_tree, iter_nodes

DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _loaded_file(filename: str) -> LoadedFile:
    path = DATA_DIR / filename
    raw = path.read_bytes()
    return LoadedFile(
        collected_file=CollectedFile(abs_path=path, relative_path=filename, language="py"),
        text=raw.decode("utf-8", errors="replace"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )


def _parse(filename: str) -> CodeNode:
    return PythonParser().parse(_loaded_file(filename))


def _parse_text(tmp_path: Path, filename: str, content: str) -> CodeNode:
    path = tmp_path / filename
    raw = content.encode("utf-8")
    return PythonParser().parse(
        LoadedFile(
            collected_file=CollectedFile(abs_path=path, relative_path=filename, language="py"),
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )


def _all_comments(root: CodeNode) -> list[dict[str, Any]]:
    return [dict(comment) for node in iter_nodes(root) for comment in node.comments]


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
    comments = _all_comments(root)
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
        function.attributes["signature"] == "foo(a: int, /, b='x', *, c: str='y', **kwargs) -> str"
    )


def test_python_ids_are_deterministic() -> None:
    first = flatten_tree(_parse("basic.py"))
    second = flatten_tree(_parse("basic.py"))
    assert [node["id"] for node in first] == [node["id"] for node in second]


def test_python_origin_ids_do_not_depend_on_name_or_end_line(tmp_path: Path) -> None:
    before = _parse_text(
        tmp_path, "sample.py", "class First:\n    def work(self):\n        return 1\n"
    )
    after = _parse_text(
        tmp_path,
        "sample.py",
        "class Renamed:\n    def work(self):\n        return 1\n        pass\n",
    )
    assert before.children[0].id == after.children[0].id
    assert before.children[0].children[0].id == after.children[0].children[0].id
    assert before.children[0].end_line != after.children[0].end_line


def test_python_origin_columns_are_characters_and_disambiguate_same_line(
    tmp_path: Path,
) -> None:
    content = "if True: π = 1; import os; import sys\n"
    root = _parse_text(tmp_path, "unicode.py", content)
    imports = [node for node in root.children if node.type == "import"]
    assert [node.start_column for node in imports] == [
        content.index("import os"),
        content.index("import sys"),
    ]
    assert imports[0].id != imports[1].id


def test_decorators_belong_to_declaration_span(tmp_path: Path) -> None:
    root = _parse_text(
        tmp_path,
        "decorated.py",
        "@decorate\nclass C:\n    @property\n    def value(self):\n        return 1\n",
    )
    cls = root.children[0]
    method = cls.children[0]
    assert (cls.start_line, cls.start_column, cls.end_line) == (1, 0, 5)
    assert (method.start_line, method.start_column, method.end_line) == (3, 4, 5)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "decorators",
    [
        "@\\\ndecorator\n",
        "@(\n    decorator\n)\n",
        "@first(\n    left @ right, '@string',\n)\n# @comment\n\n@second\n",
    ],
)
@pytest.mark.parametrize("declaration", ["def f():", "async def f():", "class f:"])
def test_multiline_decorator_origin_is_the_first_at_token(
    tmp_path: Path, newline: str, decorators: str, declaration: str
) -> None:
    content = "class Outer:\n" + "".join(
        "    " + line if line.strip() else line
        for line in (decorators + declaration + "\n    pass\n").splitlines(keepends=True)
    )
    root = _parse_text(tmp_path, "decorated.py", content.replace("\n", newline))
    declaration_node = root.children[0].children[0]
    assert (declaration_node.start_line, declaration_node.start_column) == (2, 4)
    assert declaration_node.end_line == len(content.splitlines())


def test_at_tokens_in_expressions_strings_and_comments_are_not_decorators(tmp_path: Path) -> None:
    root = _parse_text(
        tmp_path,
        "unicode.py",
        'π = "@not_a_decorator"\n# @comment\nvalue = left @ right\n'
        "def plain():\n    return value\n",
    )
    assert (root.children[0].start_line, root.children[0].start_column) == (4, 0)


def test_python_unparse_failure_keeps_parse_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_unparse(_node: object) -> str:
        raise RecursionError("synthetic depth")

    monkeypatch.setattr("repogpt.adapters.parsers.py_parser.ast.unparse", fail_unparse)
    root = _parse_text(tmp_path, "unparse.py", "def f(x: int) -> str:\n    return 'ok'\n")
    function = root.children[0]
    assert function.attributes["signature"] == "f(...)"
    assert function.attributes["returns"] is None


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
            text=content,
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        )
    )

    function = next(child for child in root.children if child.type == "function")

    assert function.attributes["signature"] == "foo(*args, kw: int, **kwargs) -> None"


def test_python_metrics_and_unicode_comments() -> None:
    root = _parse("edge_cases_comments.py")
    comments = [comment["text"] for comment in _all_comments(root)]
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

    comments = _all_comments(root)
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

    seen_comments = _all_comments(root)
    assert len(seen_comments) == len(comments)
    assert {comment["line"] for comment in seen_comments} == {entry["line"] for entry in comments}
