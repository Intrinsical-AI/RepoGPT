from __future__ import annotations

from pathlib import Path

from repogpt.adapters.parser.py_parser import PythonParser
from repogpt.models import CodeNode, ParserInput
from repogpt.utils.tree_utils import all_comments, flatten_tree


DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _parse(filename: str) -> CodeNode:
    return PythonParser().parse(
        ParserInput(
            file_path=DATA_DIR / filename,
            file_info={"relative_path": filename},
        )
    )


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
    parser = PythonParser()
    fixture = tmp_path / "tmp_imports.py"
    fixture.write_text(
        "import os as operating_system\n"
        "from pkg.sub import name as alias\n"
        "@decorator\n"
        "async def foo(a: int, /, b='x', *, c: str = 'y', **kwargs) -> str:\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    root = parser.parse(
        ParserInput(file_path=fixture, file_info={"relative_path": "tmp_imports.py"})
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
    parser = PythonParser()
    fixture = tmp_path / "tmp_signature.py"
    fixture.write_text(
        "def foo(*args, kw: int, **kwargs) -> None:\n    return None\n",
        encoding="utf-8",
    )
    root = parser.parse(
        ParserInput(file_path=fixture, file_info={"relative_path": "tmp_signature.py"})
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
    fixture.write_text("line1\nline2\n", encoding="utf-8")

    root = PythonParser().parse(
        ParserInput(file_path=fixture, file_info={"relative_path": "trailing.py"})
    )

    assert root.end_line == 2
