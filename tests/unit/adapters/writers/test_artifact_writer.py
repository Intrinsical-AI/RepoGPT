from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.domain.analysis import (
    AstProjection,
    CodeUnitsProjection,
)


def test_writer_writes_ast_json_to_file(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    projection = AstProjection(
        schema_version="1",
        json_payload={"schema_version": "1", "stats": {}, "failures": [], "records": []},
        ndjson_records=[],
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1"


def test_writer_writes_ndjson_to_stdout(capsys: Any) -> None:
    projection = AstProjection(
        schema_version="1",
        json_payload={"schema_version": "1"},
        ndjson_records=[{"record_type": "summary", "schema_version": "1", "stats": {}}],
    )

    ArtifactWriter().write(projection, None, format="ndjson")

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["record_type"] == "summary"


def test_writer_writes_code_units_to_explicit_path(tmp_path: Path) -> None:
    output = tmp_path / "units.json"
    projection = CodeUnitsProjection(
        schema_version="4",
        json_payload={"schema_version": "4", "documents": [], "failures": [], "stats": {}},
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "4"
