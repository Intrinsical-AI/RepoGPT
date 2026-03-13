from __future__ import annotations

import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import cast


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
DATA_ROOT = REPO_ROOT / "tests" / "data"
CLI_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_repo"
GOLDEN_ROOT = REPO_ROOT / "tests" / "golden"


def _run(args: list[str], repo_path: Path = DATA_ROOT) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(SRC_ROOT)
    )
    return subprocess.run(
        [sys.executable, "-m", "repogpt.app.cli", *args, str(repo_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )


def _json_lines(stdout: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _normalize_json_payload(payload: dict[str, object], repo_path: Path) -> dict[str, object]:
    normalized = cast(dict[str, object], json.loads(json.dumps(payload)))
    normalized["repo_root"] = "<REPO_ROOT>"
    for failure in cast(list[dict[str, object]], normalized["failures"]):
        failure["error"] = str(failure["error"]).replace(
            repo_path.resolve().as_posix(),
            "<REPO_ROOT>",
        )
    return normalized


def _normalize_ndjson(records: list[dict[str, object]], repo_path: Path) -> list[dict[str, object]]:
    normalized = cast(list[dict[str, object]], json.loads(json.dumps(records)))
    for record in normalized:
        if record["record_type"] == "failure":
            record["error"] = str(record["error"]).replace(
                repo_path.resolve().as_posix(), "<REPO_ROOT>"
            )
        if record["record_type"] == "summary":
            record["repo_root"] = "<REPO_ROOT>"
    return normalized


def test_cli_rejects_unsupported_language() -> None:
    proc = _run(["--languages", "ts"])
    assert proc.returncode == 2
    assert "unsupported languages" in proc.stderr


def test_cli_fail_fast_returns_exit_code_1() -> None:
    proc = _run(["--fail-fast", "--stdout", "--include-tests"])
    assert proc.returncode == 1
    assert "aborting — fail-fast" in proc.stderr


def test_cli_ndjson_stream_contains_nodes_failures_and_summary() -> None:
    proc = _run(["--stdout", "--format", "ndjson", "--flatten", "file", "--include-tests"])
    assert proc.returncode == 2
    records = _json_lines(proc.stdout)
    record_types = [record["record_type"] for record in records]
    assert "node" in record_types
    assert "failure" in record_types
    assert record_types[-1] == "summary"
    assert all(record["schema_version"] == "1" for record in records)


def test_cli_json_envelope_is_stable() -> None:
    proc = _run(["--stdout", "--format", "json", "--flatten", "node", "--include-tests"])
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "1"
    assert payload["repo_root"] == DATA_ROOT.resolve().as_posix()
    assert set(payload.keys()) == {"schema_version", "repo_root", "stats", "failures", "records"}
    assert payload["stats"]["failed_files"] == 1
    assert payload["failures"][0]["record_type"] == "failure"


def test_cli_json_matches_golden_fixture() -> None:
    proc = _run(
        ["--stdout", "--format", "json", "--flatten", "file", "--include-tests"],
        CLI_FIXTURE,
    )
    assert proc.returncode == 2
    payload = _normalize_json_payload(json.loads(proc.stdout), CLI_FIXTURE)
    expected = json.loads((GOLDEN_ROOT / "cli_fixture_json.json").read_text(encoding="utf-8"))
    assert payload == expected


def test_cli_ndjson_matches_golden_fixture() -> None:
    proc = _run(
        ["--stdout", "--format", "ndjson", "--flatten", "file", "--include-tests"],
        CLI_FIXTURE,
    )
    assert proc.returncode == 2
    records = _normalize_ndjson(_json_lines(proc.stdout), CLI_FIXTURE)
    expected = [
        json.loads(line)
        for line in (
            GOLDEN_ROOT / "cli_fixture_ndjson.ndjson"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records == expected


def test_cli_empty_repo_returns_zero_and_no_index_error() -> None:
    with TemporaryDirectory() as tmp_dir:
        proc = _run(["--stdout", "--format", "json"], Path(tmp_dir))
        assert proc.returncode == 0
        payload = json.loads(proc.stdout)
        assert payload["stats"]["total_files"] == 0
        assert payload["failures"] == []
        assert payload["records"] == []
