from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from repogpt.adapters.parsers.md_parser import MarkdownParser
from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector
from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, AnalysisStats
from repogpt.domain.errors import ParseFailure
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile, ParsedFile


def _documents(payload: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], payload["documents"])


def _document(payload: dict[str, object], index: int = 0) -> dict[str, Any]:
    return _documents(payload)[index]


def _python_parsed_file(tmp_path: Path, filename: str, content: str) -> ParsedFile:
    sample = tmp_path / filename
    sample.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")
    loaded = LoadedFile(
        collected_file=CollectedFile(abs_path=sample, relative_path=filename, language="py"),
        text=content,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    return ParsedFile(loaded_file=loaded, root=PythonParser().parse(loaded))


def _markdown_parsed_file(tmp_path: Path, filename: str, content: str) -> ParsedFile:
    sample = tmp_path / filename
    sample.write_text(content, encoding="utf-8")
    raw = content.encode("utf-8")
    loaded = LoadedFile(
        collected_file=CollectedFile(abs_path=sample, relative_path=filename, language="md"),
        text=content,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    return ParsedFile(loaded_file=loaded, root=MarkdownParser().parse(loaded))


def test_code_units_projection_contains_documents(tmp_path: Path) -> None:
    parsed_file = _python_parsed_file(
        tmp_path,
        "sample.py",
        "class Demo:\n    def method(self, value: int) -> int:\n        return value + 1\n\n"
        "def helper(name: str = 'world') -> str:\n    return name\n",
    )
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
    )

    projection = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path))
    payload = projection.json_payload

    assert payload["schema_version"] == "5"
    assert payload["kind"] == "code-units"
    assert payload["replace_scope"] is False
    assert [doc["unit_type"] for doc in payload["documents"]] == [
        "module",
        "class",
        "method",
        "function",
    ]
    assert payload["documents"][2]["external_id"] == (
        f"repogpt:{payload['repo_key']}:sample.py:method:Demo.method"
    )
    assert payload["documents"][0]["content"] == "\n"
    assert payload["documents"][0]["content_ranges"] == [{"start_line": 4, "end_line": 4}]
    assert payload["documents"][1]["unit_level"] == "container"
    assert payload["documents"][1]["qualified_name"] == "Demo"
    assert payload["documents"][1]["container_id"] == (
        f"repogpt:{payload['repo_key']}:sample.py:module"
    )
    assert payload["documents"][2]["unit_level"] == "symbol"
    assert payload["documents"][2]["qualified_name"] == "Demo.method"
    assert payload["documents"][2]["depth"] == 2
    assert payload["documents"][2]["ancestor_path"] == ["sample.py", "Demo"]
    assert payload["documents"][2]["docstring_present"] is False
    assert payload["documents"][2]["has_children"] is False
    assert payload["documents"][0]["container_id"] == payload["documents"][0]["external_id"]
    assert all(
        doc["container_id"] in {item["external_id"] for item in payload["documents"]}
        for doc in payload["documents"]
    )


def test_code_units_projection_uses_loaded_file_snapshot(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    original = "def helper(name: str = 'world') -> str:\n    return name\n"
    sample.write_text(original, encoding="utf-8")
    raw = original.encode("utf-8")
    loaded = LoadedFile(
        collected_file=CollectedFile(abs_path=sample, relative_path="sample.py", language="py"),
        text=original,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    parsed_file = ParsedFile(loaded_file=loaded, root=PythonParser().parse(loaded))
    sample.write_text("def changed():\n    return 0\n", encoding="utf-8")
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
    )

    payload = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path)).json_payload

    assert payload["documents"][0]["content"] == ""
    assert payload["documents"][0]["content_ranges"] == []
    assert payload["documents"][1]["content"].startswith("def helper")


def test_code_units_projection_failure_records_include_record_type(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("x=1\n", encoding="utf-8")
    raw = b"x=1\n"
    parsed_file = ParsedFile(
        loaded_file=LoadedFile(
            collected_file=CollectedFile(abs_path=sample, relative_path="sample.py", language="py"),
            text="x=1\n",
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        ),
        root=None,
        failure=ParseFailure("boom"),
    )
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=0, failed_files=1),
    )

    payload = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path)).json_payload

    assert payload["failures"][0]["record_type"] == "failure"
    assert payload["failures"][0]["schema_version"] == "5"


def test_code_units_projection_markdown_falls_back_to_module(tmp_path: Path) -> None:
    parsed_file = _markdown_parsed_file(tmp_path, "README.md", "plain text only\n")
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
    )

    payload = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path)).json_payload

    assert len(payload["documents"]) == 1
    assert _document(payload)["unit_type"] == "module"


def test_code_units_projection_preserves_scope_unicity_for_symbol_collisions(
    tmp_path: Path,
) -> None:
    content = """
def helper():
    return "global"


class Demo:
    def helper(self):
        return "method"

    class Inner:
        def helper(self):
            return "inner"

def outer_helper():
    pass
"""

    parsed_file = _python_parsed_file(tmp_path, "sample.py", content)
    projection = (
        CodeUnitsProjector()
        .project(
            AnalysisResult(
                parsed_files=[parsed_file],
                skipped_files=[],
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
            ),
            AnalysisRequest(repo_root=tmp_path),
        )
        .json_payload
    )

    documents = _documents(projection)
    external_ids = [document["external_id"] for document in documents]
    qualified_names = [document["qualified_name"] for document in documents]

    assert len(external_ids) == len(set(external_ids))
    assert len(qualified_names) == len(set(qualified_names))
    helpers = [document for document in documents if document["symbol"] == "helper"]
    assert {document["unit_type"] for document in helpers} == {"function", "method"}
    assert any(document["unit_type"] == "function" for document in helpers)
    assert any(document["unit_type"] == "method" for document in helpers)
    assert any(document["qualified_name"] == "helper" for document in helpers)
    assert any(document["qualified_name"] == "Demo.helper" for document in helpers)
    assert any(document["qualified_name"] == "Demo.Inner.helper" for document in helpers)


def test_code_units_projection_markdown_duplicate_headings_are_ordinalized(tmp_path: Path) -> None:
    parsed_file = _markdown_parsed_file(
        tmp_path,
        "README.md",
        "# Title\n"
        "## Details\n"
        "Some text\n"
        "## Details\n"
        "Other text\n"
        "### Subheading\n"
        "## Details\n"
        "Third\n",
    )

    projection = (
        CodeUnitsProjector()
        .project(
            AnalysisResult(
                parsed_files=[parsed_file],
                skipped_files=[],
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
            ),
            AnalysisRequest(repo_root=tmp_path),
        )
        .json_payload
    )

    qualified_names = [document["qualified_name"] for document in _documents(projection)]
    heading_names = [
        name for name in qualified_names if name.startswith("title") or "details" in name
    ]

    assert "title/details" in heading_names
    assert "title/details-2" in heading_names
    assert "title/details-3" in heading_names


def test_code_units_projection_is_stable_with_unicode_path_and_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "códigö.py"
    content = "def hello() -> str:\n    # salutación\n    return 'ok'\n".encode()
    path.write_bytes(content)
    raw = path.read_bytes()

    sample = LoadedFile(
        collected_file=CollectedFile(
            abs_path=path,
            relative_path=path.name,
            language="py",
        ),
        text=raw.decode("utf-8"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    parsed_file = ParsedFile(loaded_file=sample, root=PythonParser().parse(sample))
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
    )

    first_request = AnalysisRequest(repo_root=tmp_path)
    second_request = AnalysisRequest(repo_root=tmp_path)
    projection = CodeUnitsProjector().project(result, first_request).json_payload
    projection2 = CodeUnitsProjector().project(result, second_request).json_payload
    documents = _documents(projection)
    documents2 = _documents(projection2)

    assert documents[1]["path"] == path.name
    assert documents == documents2
    content_hash = hashlib.sha256(documents[1]["content"].encode("utf-8")).hexdigest()
    assert content_hash == documents[1]["content_hash"]
    assert "salutación" in documents[1]["content"]


def test_module_residual_keeps_unselected_lines_and_nested_container(tmp_path: Path) -> None:
    content = (
        '"""Module notes."""\r\n'
        "import os\r\n"
        "CONSTANT = 3\r\n"
        "\r\n"
        "def outer():\r\n"
        "    def inner():\r\n"
        "        return CONSTANT\r\n"
        "    return inner()\r\n"
        "\r\n"
        'if __name__ == "__main__":\r\n'
        "    print(outer())\r\n"
    )
    parsed = _python_parsed_file(tmp_path, "sample.py", content)
    payload = (
        CodeUnitsProjector()
        .project(
            AnalysisResult(
                parsed_files=[parsed],
                skipped_files=[],
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
            ),
            AnalysisRequest(repo_root=tmp_path),
        )
        .json_payload
    )
    module, outer, inner = _documents(payload)
    assert module["content"] == (
        '"""Module notes."""\r\nimport os\r\nCONSTANT = 3\r\n\r\n'
        '\r\nif __name__ == "__main__":\r\n    print(outer())\r\n'
    )
    assert module["content_ranges"] == [
        {"start_line": 1, "end_line": 4},
        {"start_line": 9, "end_line": 11},
    ]
    assert (module["start_line"], module["end_line"]) == (1, 11)
    assert module["content_hash"] == hashlib.sha256(module["content"].encode()).hexdigest()
    assert outer["content"] == "".join(content.splitlines(keepends=True)[4:8])
    assert inner["container_id"] == outer["external_id"]
    assert outer["unit_level"] == "container"
    assert inner["unit_level"] == "symbol"
    assert all(
        doc["container_id"] in {item["external_id"] for item in _documents(payload)}
        for doc in _documents(payload)
    )


def test_decorators_belong_to_callable_span_not_module_residual(tmp_path: Path) -> None:
    parsed = _python_parsed_file(
        tmp_path,
        "sample.py",
        "import functools\n\n@functools.cache\ndef f():\n    return 1\n",
    )
    payload = (
        CodeUnitsProjector()
        .project(
            AnalysisResult(
                parsed_files=[parsed],
                skipped_files=[],
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
            ),
            AnalysisRequest(repo_root=tmp_path),
        )
        .json_payload
    )
    module, function = _documents(payload)
    assert module["content"] == "import functools\n\n"
    assert module["content_ranges"] == [{"start_line": 1, "end_line": 2}]
    assert function["start_line"] == 3
    assert function["content"] == "@functools.cache\ndef f():\n    return 1\n"


def test_markdown_preamble_residual_and_code_fence_symbol(tmp_path: Path) -> None:
    parsed = _markdown_parsed_file(
        tmp_path, "README.md", "Intro\n\n# Heading\n```python\nprint(1)\n```\n"
    )
    payload = (
        CodeUnitsProjector()
        .project(
            AnalysisResult(
                parsed_files=[parsed],
                skipped_files=[],
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0),
            ),
            AnalysisRequest(repo_root=tmp_path),
        )
        .json_payload
    )
    module, heading, code = _documents(payload)
    assert module["content"] == "Intro\n\n"
    assert module["content_ranges"] == [{"start_line": 1, "end_line": 2}]
    assert heading["container_id"] == module["external_id"]
    assert code["container_id"] == heading["external_id"]
    assert code["symbol"] is None
