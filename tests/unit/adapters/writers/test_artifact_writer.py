from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.domain.analysis import (
    AstProjection,
    CodeUnitsProjection,
)


def test_writer_writes_ast_json_to_file(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    projection = AstProjection(
        json_payload={"schema_version": "2", "stats": {}, "failures": [], "records": []},
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"


def test_writer_writes_ndjson_to_stdout(capsys: Any) -> None:
    projection = AstProjection(
        json_payload={
            "schema_version": "2",
            "repo_root": ".",
            "stats": {},
            "failures": [],
            "records": [],
        },
    )

    ArtifactWriter().write(projection, None, format="ndjson")

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["record_type"] == "summary"


def test_writer_writes_code_units_to_explicit_path(tmp_path: Path) -> None:
    output = tmp_path / "units.json"
    projection = CodeUnitsProjection(
        json_payload={"schema_version": "5", "documents": [], "failures": [], "stats": {}},
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "5"


@pytest.mark.parametrize("umask,expected", [(0o022, 0o644), (0o077, 0o600)])
def test_writer_new_file_uses_umask(tmp_path: Path, umask: int, expected: int) -> None:
    output = tmp_path / "out.json"
    projection = AstProjection(json_payload={})
    previous_umask = os.umask(umask)
    try:
        ArtifactWriter().write(projection, output)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(output.stat().st_mode) == expected
