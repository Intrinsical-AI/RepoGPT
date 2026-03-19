from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.domain.analysis import (
    AnalysisRequest,
    AstProjection,
    CodeUnitsProjection,
    OutputTarget,
)


def test_writer_writes_ast_json_to_file(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    projection = AstProjection(
        schema_version="1",
        json_payload={"schema_version": "1", "stats": {}, "failures": [], "records": []},
        ndjson_records=[],
    )

    ArtifactWriter().write(
        projection,
        AnalysisRequest(repo_root=tmp_path, output_target=OutputTarget(path=output)),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"


def test_writer_writes_ndjson_to_stdout(tmp_path: Path, capsys: Any) -> None:
    projection = AstProjection(
        schema_version="1",
        json_payload={"schema_version": "1"},
        ndjson_records=[{"record_type": "summary", "schema_version": "1", "stats": {}}],
    )

    ArtifactWriter().write(
        projection,
        AnalysisRequest(
            repo_root=tmp_path,
            format="ndjson",
            output_target=OutputTarget(to_stdout=True),
        ),
    )

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["record_type"] == "summary"


def test_writer_defaults_code_units_filename(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    projection = CodeUnitsProjection(
        schema_version="3",
        json_payload={"schema_version": "3", "documents": [], "failures": [], "stats": {}},
    )

    ArtifactWriter().write(projection, AnalysisRequest(repo_root=tmp_path, projection="code_units"))

    payload = json.loads((tmp_path / "code_units.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "3"
