from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from repogpt.mcp_server import handle_request

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
CLI_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_repo"


def _run(args: list[str], repo_path: Path = CLI_FIXTURE) -> subprocess.CompletedProcess[str]:
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


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_content_text(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]  # type: ignore[index]
    content = result["content"]  # type: ignore[index]
    return json.loads(content[0]["text"])  # type: ignore[index]


def test_mcp_initialize_and_list_tools() -> None:
    initialize = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialize["result"]["serverInfo"]["name"] == "repogpt"  # type: ignore[index]

    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listed["result"]["tools"]}  # type: ignore[index]
    assert {
        "repogpt_emit_code_units",
        "repogpt_emit_ast",
        "repogpt_compare_profiles",
    } <= names


def test_mcp_emit_code_units_matches_cli_output() -> None:
    cli_run = _run(
        ["--stdout", "--format", "json", "--emit", "code-units", "--include-tests"], CLI_FIXTURE
    )
    assert cli_run.returncode == 2
    cli_payload = json.loads(cli_run.stdout)

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_code_units",
                "arguments": {
                    "repo_path": str(CLI_FIXTURE),
                    "include_tests": True,
                },
            },
        }
    )

    payload = _extract_content_text(response)
    assert payload["exit_code"] == 2
    assert payload["artifact"] == cli_payload


def test_mcp_emit_ast_supports_ndjson() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_ast",
                "arguments": {
                    "repo_path": str(CLI_FIXTURE),
                    "format": "ndjson",
                    "flatten": "file",
                    "include_tests": True,
                },
            },
        }
    )

    payload = _extract_content_text(response)
    assert payload["exit_code"] == 2
    records = payload["artifact"]
    assert isinstance(records, list)
    assert records[-1]["record_type"] == "summary"


def test_mcp_compare_profiles_uses_code_units_artifact(tmp_path: Path) -> None:
    artifact_path = tmp_path / "code_units.json"
    artifact = _run(
        ["--format", "json", "--emit", "code-units", "-o", str(artifact_path)], CLI_FIXTURE
    )
    assert artifact.returncode == 2

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "repogpt_compare_profiles",
                "arguments": {
                    "artifact_path": str(artifact_path),
                    "query": "helper",
                },
            },
        }
    )

    payload = _extract_content_text(response)
    comparison = payload["comparison"]
    assert payload["exit_code"] == 0
    assert comparison["query_text"] == "helper"
    assert "flat_rag_v1" in comparison
    assert "structured_rag_v1" in comparison
    assert _read_json(artifact_path)["kind"] == "code-units"
