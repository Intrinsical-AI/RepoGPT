from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repogpt.adapters.publisher.simple_publisher import SCHEMA_VERSION, SimplePublisher
from repogpt.models import AnalysisConf, CodeNode, PipelineResult


def _result(*, root: CodeNode | None, path: str = "test.py") -> PipelineResult:
    return PipelineResult(
        path=Path(path),
        language="py",
        root=root,
        error=None if root is not None else "boom",
        file_info={
            "relative_path": path,
            "size": 100,
            "sha256": "abc123",
        },
    )


def _node() -> CodeNode:
    return CodeNode(
        id="node-1",
        type="module",
        name="test",
        language="py",
        path="test.py",
        start_line=1,
        end_line=1,
        children=[],
    )


def test_publish_json_envelope(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    conf = AnalysisConf(
        repo_path=tmp_path,
        output=output,
        output_format="json",
        flatten_kind="node",
    )

    SimplePublisher().publish([_result(root=_node())], conf)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["repo_root"] == tmp_path.resolve().as_posix()
    assert payload["failures"] == []
    assert payload["stats"]["ok_files"] == 1
    assert payload["stats"]["failed_files"] == 0
    assert payload["records"][0]["record_type"] == "node"
    assert payload["records"][0]["path"] == "test.py"
    assert payload["records"][0]["language"] == "py"
    assert "lang" not in payload["records"][0]


def test_publish_ndjson_contract(tmp_path: Path) -> None:
    output = tmp_path / "out.ndjson"
    conf = AnalysisConf(
        repo_path=tmp_path,
        output=output,
        output_format="ndjson",
        flatten_kind="node",
    )

    SimplePublisher().publish([_result(root=_node()), _result(root=None, path="bad.py")], conf)

    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [record["record_type"] for record in records] == [
        "node",
        "failure",
        "summary",
    ]
    assert records[0]["schema_version"] == SCHEMA_VERSION
    assert records[1]["path"] == "bad.py"
    assert records[2]["stats"]["failed_files"] == 1


def test_publish_stdout_json(capsys: Any) -> None:
    conf = AnalysisConf(
        repo_path=Path.cwd(),
        to_stdout=True,
        output_format="json",
        flatten_kind="node",
    )

    SimplePublisher().publish([_result(root=_node())], conf)

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["records"][0]["id"] == "node-1"


def test_publish_empty_results(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    conf = AnalysisConf(
        repo_path=tmp_path,
        output=output,
        output_format="json",
        flatten_kind="node",
    )

    SimplePublisher().publish([], conf)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["records"] == []
    assert payload["failures"] == []
    assert payload["stats"]["total_files"] == 0
