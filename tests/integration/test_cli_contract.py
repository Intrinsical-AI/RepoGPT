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
        f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(SRC_ROOT)
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


def _normalize_code_units_payload(payload: dict[str, object], repo_path: Path) -> dict[str, object]:
    normalized = cast(dict[str, object], json.loads(json.dumps(payload)))
    normalized["snapshot_id"] = "<SNAPSHOT_ID>"
    for document in cast(list[dict[str, object]], normalized["documents"]):
        document["snapshot_id"] = "<SNAPSHOT_ID>"
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


def test_cli_empty_languages_means_collect_nothing() -> None:
    proc = _run(["--languages", "", "--stdout", "--format", "json"], CLI_FIXTURE)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["stats"]["total_files"] == 0
    assert payload["records"] == []


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


def test_cli_code_units_matches_golden_fixture() -> None:
    proc = _run(
        ["--stdout", "--format", "json", "--emit", "code-units", "--include-tests"],
        CLI_FIXTURE,
    )
    assert proc.returncode == 2
    payload = _normalize_code_units_payload(json.loads(proc.stdout), CLI_FIXTURE)
    assert payload["schema_version"] == "2"
    expected = json.loads((GOLDEN_ROOT / "cli_fixture_code_units.json").read_text(encoding="utf-8"))
    assert payload == expected


def test_cli_code_units_documents_are_consumable_without_metadata() -> None:
    proc = _run(
        ["--stdout", "--format", "json", "--emit", "code-units", "--include-tests"],
        CLI_FIXTURE,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    document = payload["documents"][0]

    assert payload["schema_version"] == "2"
    assert {
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
    }.issubset(document.keys())
    assert "path" not in document["metadata"]
    assert "unit_type" not in document["metadata"]


def test_cli_ndjson_matches_golden_fixture() -> None:
    proc = _run(
        ["--stdout", "--format", "ndjson", "--flatten", "file", "--include-tests"],
        CLI_FIXTURE,
    )
    assert proc.returncode == 2
    records = _normalize_ndjson(_json_lines(proc.stdout), CLI_FIXTURE)
    expected = [
        json.loads(line)
        for line in (GOLDEN_ROOT / "cli_fixture_ndjson.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
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


def test_cli_missing_repo_path_returns_clean_exit_code_3() -> None:
    missing = REPO_ROOT / "does-not-exist"
    proc = _run(["--stdout", "--format", "json"], missing)

    assert proc.returncode == 3
    assert "invalid repository path" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_file_repo_path_returns_clean_exit_code_3() -> None:
    with TemporaryDirectory() as tmp_dir:
        repo_file = Path(tmp_dir) / "repo.py"
        repo_file.write_text("x=1", encoding="utf-8")

        proc = _run(["--stdout", "--format", "json"], repo_file)

    assert proc.returncode == 3
    assert "invalid repository path" in proc.stderr
    assert "Traceback" not in proc.stderr
