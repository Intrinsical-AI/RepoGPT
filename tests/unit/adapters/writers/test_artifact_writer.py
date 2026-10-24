from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Literal

import pytest

from repogpt.adapters.writers.artifact_writer import ArtifactWriter, ArtifactWriteReceipt
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


def test_receipt_check_sees_exact_bytes_before_publication_and_can_refuse(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous artifact")
    seen: list[ArtifactWriteReceipt] = []

    def check(receipt: ArtifactWriteReceipt) -> None:
        assert output.read_bytes() == b"previous artifact"
        prepared = next(tmp_path.glob(".out.json.*.tmp")).read_bytes()
        assert receipt.sha256 == hashlib.sha256(prepared).hexdigest()
        assert receipt.size_bytes == len(prepared)
        seen.append(receipt)
        raise ValueError("receipt refused")

    with pytest.raises(ValueError, match="receipt refused"):
        ArtifactWriter().write(AstProjection(json_payload={}), output, receipt_check=check)

    assert len(seen) == 1
    assert output.read_bytes() == b"previous artifact"
    assert list(tmp_path.iterdir()) == [output]


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
def test_writer_fsyncs_flushed_bytes_before_replacing_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: Literal["json", "ndjson"]
) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous artifact")
    projection = AstProjection(
        json_payload={
            "schema_version": "3",
            "repo_root": ".",
            "records": [],
            "failures": [],
            "stats": {},
        }
    )
    synchronized: list[bytes] = []
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        assert output.read_bytes() == b"previous artifact"
        temporary_files = list(tmp_path.glob(".out.json.*.tmp"))
        assert len(temporary_files) == 1
        payload = temporary_files[0].read_bytes()
        assert payload
        assert os.fstat(fd).st_size == len(payload)
        real_fsync(fd)
        synchronized.append(payload)

    monkeypatch.setattr(os, "fsync", fsync)

    ArtifactWriter().write(projection, output, format=format)

    assert synchronized == [output.read_bytes()]


@pytest.mark.parametrize("format", ["json", "ndjson"])
def test_writer_fsync_error_preserves_destination_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: Literal["json", "ndjson"]
) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous artifact")
    output.chmod(0o640)

    def fsync(fd: int) -> None:
        raise OSError(errno.EIO, "injected fsync failure")

    monkeypatch.setattr(os, "fsync", fsync)

    with pytest.raises(OSError, match="failed to write artifact") as error:
        ArtifactWriter().write(
            AstProjection(
                json_payload={
                    "schema_version": "3",
                    "repo_root": ".",
                    "records": [],
                    "failures": [],
                    "stats": {},
                }
            ),
            output,
            format=format,
        )

    assert error.value.errno == errno.EIO
    assert output.read_bytes() == b"previous artifact"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert list(tmp_path.iterdir()) == [output]


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
