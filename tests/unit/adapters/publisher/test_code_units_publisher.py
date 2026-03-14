from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from repogpt.adapters.parser.md_parser import MarkdownParser
from repogpt.adapters.parser.py_parser import PythonParser
from repogpt.adapters.publisher.code_units_publisher import CodeUnitsPublisher
from repogpt.models import AnalysisConf, CodeNode, ParserInput, PipelineResult


def _fixture_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(
        "class Demo:\n"
        "    def method(self, value: int) -> int:\n"
        "        return value + 1\n"
        "\n"
        "def helper(name: str = 'world') -> str:\n"
        "    return name\n",
        encoding="utf-8",
    )
    return path


def _publish_payload(
    *,
    tmp_path: Path,
    results: list[PipelineResult],
) -> dict[str, object]:
    output = tmp_path / "code_units.json"
    CodeUnitsPublisher().publish(
        results,
        AnalysisConf(repo_path=tmp_path, output=output, emit_kind="code-units"),
    )
    return cast(dict[str, object], json.loads(output.read_text(encoding="utf-8")))


def _documents(payload: dict[str, object]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], payload["documents"])


def _document(payload: dict[str, object], index: int = 0) -> dict[str, Any]:
    return _documents(payload)[index]


def _python_result(tmp_path: Path, filename: str, content: str) -> PipelineResult:
    sample = tmp_path / filename
    sample.write_text(content, encoding="utf-8")
    root = PythonParser().parse(
        ParserInput(
            file_path=sample,
            file_info={
                "relative_path": filename,
                "size": sample.stat().st_size,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
            content=content,
        )
    )
    return PipelineResult(
        path=sample,
        language="py",
        root=root,
        file_info={
            "relative_path": filename,
            "size": sample.stat().st_size,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
        content=content,
    )


def _markdown_result(tmp_path: Path, filename: str, content: str) -> PipelineResult:
    sample = tmp_path / filename
    sample.write_text(content, encoding="utf-8")
    root = MarkdownParser().parse(
        ParserInput(
            file_path=sample,
            file_info={
                "relative_path": filename,
                "size": sample.stat().st_size,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            },
            content=content,
        )
    )
    return PipelineResult(
        path=sample,
        language="md",
        root=root,
        file_info={
            "relative_path": filename,
            "size": sample.stat().st_size,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        },
        content=content,
    )


def test_publish_code_units_json(tmp_path: Path) -> None:
    sample = _fixture_file(tmp_path)
    method = CodeNode(
        id="method-1",
        type="method",
        name="method",
        language="py",
        path="sample.py",
        start_line=2,
        end_line=3,
        parent_id="class-1",
        attributes={"signature": "method(self, value: int) -> int"},
    )
    klass = CodeNode(
        id="class-1",
        type="class",
        name="Demo",
        language="py",
        path="sample.py",
        start_line=1,
        end_line=3,
        children=[method],
    )
    helper = CodeNode(
        id="function-1",
        type="function",
        name="helper",
        language="py",
        path="sample.py",
        start_line=5,
        end_line=6,
    )
    root = CodeNode(
        id="module-1",
        type="module",
        name="sample",
        language="py",
        path="sample.py",
        start_line=1,
        end_line=6,
        children=[klass, helper],
    )
    result = PipelineResult(
        path=sample,
        language="py",
        root=root,
        file_info={
            "relative_path": "sample.py",
            "size": sample.stat().st_size,
            "sha256": "abc123",
        },
        content=sample.read_text(encoding="utf-8"),
    )
    output = tmp_path / "code_units.json"
    conf = AnalysisConf(repo_path=tmp_path, output=output, emit_kind="code-units")

    CodeUnitsPublisher().publish([result], conf)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"
    assert payload["kind"] == "code-units"
    assert payload["repo_key"] == tmp_path.name.lower()
    assert payload["scope"] == f"repogpt:{tmp_path.name.lower()}"
    assert payload["stats"]["emitted_documents"] == 3
    assert [doc["unit_type"] for doc in payload["documents"]] == [
        "class",
        "method",
        "function",
    ]
    assert payload["documents"][1]["external_id"] == (
        f"repogpt:{tmp_path.name.lower()}:sample.py:method:Demo.method"
    )
    assert payload["documents"][1]["path"] == "sample.py"
    assert payload["documents"][1]["content"] == (
        "    def method(self, value: int) -> int:\n        return value + 1\n"
    )
    assert (
        payload["documents"][1]["content_hash"]
        == hashlib.sha256(
            payload["documents"][1]["content"].encode("utf-8")
        ).hexdigest()
    )
    assert (
        payload["documents"][1]["source_id"]
        == f"repogpt:{tmp_path.name.lower()}:file:sample.py"
    )
    assert set(payload["documents"][1]["metadata"].keys()) == {
        "file",
        "tags",
        "attributes",
        "dependencies",
    }


def test_publish_code_units_falls_back_to_module_for_markdown_without_units(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "README.md"
    sample.write_text("plain text only\n", encoding="utf-8")
    root = CodeNode(
        id="module-1",
        type="module",
        name="README",
        language="md",
        path="README.md",
        start_line=1,
        end_line=1,
    )
    result = PipelineResult(
        path=sample,
        language="md",
        root=root,
        file_info={
            "relative_path": "README.md",
            "size": sample.stat().st_size,
            "sha256": "def456",
        },
        content=sample.read_text(encoding="utf-8"),
    )
    output = tmp_path / "code_units.json"
    conf = AnalysisConf(repo_path=tmp_path, output=output, emit_kind="code-units")

    CodeUnitsPublisher().publish([result], conf)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["documents"]) == 1
    assert payload["documents"][0]["unit_type"] == "module"
    assert payload["documents"][0]["external_id"] == (
        f"repogpt:{tmp_path.name.lower()}:README.md:module"
    )


def test_publish_code_units_uses_pipeline_content_snapshot(tmp_path: Path) -> None:
    sample = _fixture_file(tmp_path)
    original_content = sample.read_text(encoding="utf-8")
    helper = CodeNode(
        id="function-1",
        type="function",
        name="helper",
        language="py",
        path="sample.py",
        start_line=5,
        end_line=6,
    )
    root = CodeNode(
        id="module-1",
        type="module",
        name="sample",
        language="py",
        path="sample.py",
        start_line=1,
        end_line=6,
        children=[helper],
    )
    result = PipelineResult(
        path=sample,
        language="py",
        root=root,
        file_info={
            "relative_path": "sample.py",
            "size": sample.stat().st_size,
            "sha256": "abc123",
        },
        content=original_content,
    )
    sample.write_text("def changed():\n    return 0\n", encoding="utf-8")
    output = tmp_path / "code_units.json"

    CodeUnitsPublisher().publish(
        [result],
        AnalysisConf(repo_path=tmp_path, output=output, emit_kind="code-units"),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["documents"][0]["symbol"] == "helper"
    assert payload["documents"][0]["content"] == (
        "def helper(name: str = 'world') -> str:\n    return name\n"
    )


def test_publish_code_units_failure_records_include_record_type(tmp_path: Path) -> None:
    sample = _fixture_file(tmp_path)
    output = tmp_path / "code_units.json"
    result = PipelineResult(
        path=sample,
        language="py",
        root=None,
        error="boom",
        file_info={
            "relative_path": "sample.py",
            "size": sample.stat().st_size,
            "sha256": "abc123",
        },
        content=sample.read_text(encoding="utf-8"),
    )

    CodeUnitsPublisher().publish(
        [result],
        AnalysisConf(repo_path=tmp_path, output=output, emit_kind="code-units"),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["failures"][0]["record_type"] == "failure"
    assert payload["failures"][0]["schema_version"] == "2"


def test_publish_code_units_defaults_to_file_without_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sample = _fixture_file(tmp_path)
    result = PipelineResult(
        path=sample,
        language="py",
        root=CodeNode(
            id="module-1",
            type="module",
            name="sample",
            language="py",
            path="sample.py",
            start_line=1,
            end_line=6,
        ),
        file_info={
            "relative_path": "sample.py",
            "size": sample.stat().st_size,
            "sha256": "abc123",
        },
        content=sample.read_text(encoding="utf-8"),
    )
    monkeypatch.chdir(tmp_path)

    CodeUnitsPublisher().publish(
        [result],
        AnalysisConf(repo_path=tmp_path, emit_kind="code-units"),
    )

    assert (tmp_path / "code_units.json").exists()


def test_code_units_expose_canonical_fields_at_document_top_level(
    tmp_path: Path,
) -> None:
    payload = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _python_result(tmp_path, "sample.py", "def helper():\n    return 1\n")
        ],
    )

    document = _document(payload)

    assert set(document.keys()) == {
        "external_id",
        "source_id",
        "repo_key",
        "scope",
        "snapshot_id",
        "path",
        "language",
        "unit_type",
        "symbol",
        "start_line",
        "end_line",
        "content",
        "content_hash",
        "metadata",
    }
    assert "path" not in document["metadata"]
    assert "snapshot_id" not in document["metadata"]
    assert "unit_type" not in document["metadata"]


def test_code_units_content_hash_changes_with_content_but_external_id_does_not(
    tmp_path: Path,
) -> None:
    first = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _python_result(tmp_path, "sample.py", "def helper():\n    return 1\n")
        ],
    )
    second = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _python_result(tmp_path, "sample.py", "def helper():\n    return 2\n")
        ],
    )

    first_doc = _document(first)
    second_doc = _document(second)

    assert first_doc["external_id"] == second_doc["external_id"]
    assert first_doc["content_hash"] != second_doc["content_hash"]


def test_python_external_id_is_stable_when_function_is_shifted_by_leading_lines(
    tmp_path: Path,
) -> None:
    first = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _python_result(tmp_path, "sample.py", "def helper():\n    return 1\n")
        ],
    )
    second = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _python_result(tmp_path, "sample.py", "\n\n\ndef helper():\n    return 1\n")
        ],
    )

    assert _document(first)["external_id"] == _document(second)["external_id"]


def test_markdown_heading_external_id_uses_heading_path(tmp_path: Path) -> None:
    payload = _publish_payload(
        tmp_path=tmp_path,
        results=[
            _markdown_result(
                tmp_path,
                "guide.md",
                "# Intro\n## Repeat\nText\n## Repeat\nMore\n",
            )
        ],
    )

    heading_ids = [
        doc["external_id"]
        for doc in _documents(payload)
        if doc["unit_type"] == "heading"
    ]

    assert heading_ids == [
        f"repogpt:{tmp_path.name.lower()}:guide.md:heading:intro",
        f"repogpt:{tmp_path.name.lower()}:guide.md:heading:intro/repeat",
        f"repogpt:{tmp_path.name.lower()}:guide.md:heading:intro/repeat-2",
    ]


def test_markdown_code_block_external_id_is_stable_within_same_section_ordinal(
    tmp_path: Path,
) -> None:
    content = "# Intro\n```py\nprint(1)\n```\n"
    first = _publish_payload(
        tmp_path=tmp_path,
        results=[_markdown_result(tmp_path, "guide.md", content)],
    )
    second = _publish_payload(
        tmp_path=tmp_path,
        results=[_markdown_result(tmp_path, "guide.md", content.replace("1", "2"))],
    )

    first_code_block = next(
        doc for doc in _documents(first) if doc["unit_type"] == "code_block"
    )
    second_code_block = next(
        doc for doc in _documents(second) if doc["unit_type"] == "code_block"
    )

    assert first_code_block["external_id"] == second_code_block["external_id"]
    assert first_code_block["content_hash"] != second_code_block["content_hash"]


def test_snapshot_id_can_change_while_document_content_hash_stays_stable(
    tmp_path: Path,
) -> None:
    primary = _python_result(tmp_path, "sample.py", "def helper():\n    return 1\n")
    other_v1 = PipelineResult(
        path=tmp_path / "other.py",
        language="py",
        root=CodeNode(
            id="other", type="module", name="other", language="py", path="other.py"
        ),
        file_info={"relative_path": "other.py", "size": 1, "sha256": "aaa"},
        content="x",
    )
    other_v2 = PipelineResult(
        path=tmp_path / "other.py",
        language="py",
        root=CodeNode(
            id="other", type="module", name="other", language="py", path="other.py"
        ),
        file_info={"relative_path": "other.py", "size": 1, "sha256": "bbb"},
        content="y",
    )

    first = _publish_payload(tmp_path=tmp_path, results=[primary, other_v1])
    second = _publish_payload(tmp_path=tmp_path, results=[primary, other_v2])

    first_doc = _document(first)
    second_doc = _document(second)
    assert first["snapshot_id"] != second["snapshot_id"]
    assert first_doc["snapshot_id"] != second_doc["snapshot_id"]
    assert first_doc["content_hash"] == second_doc["content_hash"]
