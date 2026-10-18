from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Literal

import pytest

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.domain.analysis import (
    AstProjection,
    CodeUnitsProjection,
)


def test_writer_writes_ast_json_to_file(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    projection = AstProjection(
        json_payload={"schema_version": "3", "stats": {}, "failures": [], "records": []},
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "3"


def test_writer_writes_ndjson_to_stdout(capsys: Any) -> None:
    projection = AstProjection(
        json_payload={
            "schema_version": "3",
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
        json_payload={"schema_version": "6", "documents": [], "failures": [], "stats": {}},
    )

    ArtifactWriter().write(projection, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "6"


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


@pytest.mark.parametrize("format", ["json", "ndjson"])
def test_writer_returns_immutable_receipt_for_exact_utf8_bytes(
    tmp_path: Path, format: Literal["json", "ndjson"]
) -> None:
    projection = AstProjection(
        json_payload={
            "schema_version": "3",
            "repo_root": "café/🙂",
            "stats": {},
            "failures": [],
            "records": [],
        }
    )
    output = tmp_path / "artifact.json"

    receipt = ArtifactWriter().write(projection, output, format=format)

    assert receipt is not None
    raw = output.read_bytes()
    assert receipt.size_bytes == len(raw)
    assert receipt.sha256 == hashlib.sha256(raw).hexdigest()
    attribute = "size_bytes"
    with pytest.raises(FrozenInstanceError):
        setattr(receipt, attribute, 0)
