from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

from repogpt.adapters.parsers.md_parser import MarkdownParser
from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector, _extract_span_text
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
        raw_bytes=raw,
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
        raw_bytes=raw,
        text=content,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    return ParsedFile(loaded_file=loaded, root=MarkdownParser().parse(loaded))


def test_extract_span_text_returns_exact_lines() -> None:
    content = "a\nb\nc\n"
    lines = content.splitlines(keepends=True)
    assert _extract_span_text(content=content, lines=lines, start_line=2, end_line=3) == "b\nc\n"


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
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
    )

    projection = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path))
    payload = projection.json_payload

    assert payload["schema_version"] == "4"
    assert payload["kind"] == "code-units"
    assert payload["replace_scope"] is True
    assert [doc["unit_type"] for doc in payload["documents"]] == ["class", "method", "function"]
    assert payload["documents"][1]["external_id"] == (
        f"repogpt:{tmp_path.name.lower()}:sample.py:method:Demo.method"
    )
    assert payload["documents"][0]["unit_level"] == "container"
    assert payload["documents"][0]["qualified_name"] == "Demo"
    assert payload["documents"][0]["container_id"] == (
        f"repogpt:{tmp_path.name.lower()}:sample.py:module"
    )
    assert payload["documents"][1]["unit_level"] == "symbol"
    assert payload["documents"][1]["qualified_name"] == "Demo.method"
    assert payload["documents"][1]["depth"] == 2
    assert payload["documents"][1]["ancestor_path"] == ["sample.py", "Demo"]
    assert payload["documents"][1]["docstring_present"] is False
    assert payload["documents"][1]["has_children"] is False


def test_code_units_projection_uses_loaded_file_snapshot(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    original = "def helper(name: str = 'world') -> str:\n    return name\n"
    sample.write_text(original, encoding="utf-8")
    raw = original.encode("utf-8")
    loaded = LoadedFile(
        collected_file=CollectedFile(abs_path=sample, relative_path="sample.py", language="py"),
        raw_bytes=raw,
        text=original,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    parsed_file = ParsedFile(loaded_file=loaded, root=PythonParser().parse(loaded))
    sample.write_text("def changed():\n    return 0\n", encoding="utf-8")
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
    )

    payload = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path)).json_payload

    assert payload["documents"][0]["content"].startswith("def helper")


def test_code_units_projection_failure_records_include_record_type(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text("x=1\n", encoding="utf-8")
    raw = b"x=1\n"
    parsed_file = ParsedFile(
        loaded_file=LoadedFile(
            collected_file=CollectedFile(abs_path=sample, relative_path="sample.py", language="py"),
            raw_bytes=raw,
            text="x=1\n",
            digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        ),
        root=None,
        failure=ParseFailure("boom"),
    )
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=0, failed_files=1, skipped_files=0),
    )

    payload = CodeUnitsProjector().project(result, AnalysisRequest(repo_root=tmp_path)).json_payload

    assert payload["failures"][0]["record_type"] == "failure"
    assert payload["failures"][0]["schema_version"] == "4"


def test_code_units_projection_markdown_falls_back_to_module(tmp_path: Path) -> None:
    parsed_file = _markdown_parsed_file(tmp_path, "README.md", "plain text only\n")
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
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
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
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
                stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
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


def test_code_units_projection_is_stable_with_unicode_path_and_invalid_utf8_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "códigö.py"
    content = b"def hello() -> str:\n    # saludo\xff\n    return 'ok'\n"
    path.write_bytes(content)
    raw = path.read_bytes()

    sample = LoadedFile(
        collected_file=CollectedFile(
            abs_path=path,
            relative_path=path.name,
            language="py",
        ),
        raw_bytes=raw,
        text=raw.decode("utf-8", errors="replace"),
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )
    parsed_file = ParsedFile(loaded_file=sample, root=PythonParser().parse(sample))
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
    )

    first_request = AnalysisRequest(repo_root=tmp_path)
    second_request = AnalysisRequest(repo_root=tmp_path)
    projection = CodeUnitsProjector().project(result, first_request).json_payload
    projection2 = CodeUnitsProjector().project(result, second_request).json_payload
    documents = _documents(projection)
    documents2 = _documents(projection2)

    assert documents[0]["path"] == path.name
    assert documents == documents2
    content_hash = hashlib.sha256(documents[0]["content"].encode("utf-8")).hexdigest()
    assert content_hash == documents[0]["content_hash"]
    assert "�" in documents[0]["content"]
