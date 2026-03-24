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
