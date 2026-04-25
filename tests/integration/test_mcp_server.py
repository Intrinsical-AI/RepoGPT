from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import repogpt
from repogpt.mcp_server import handle_request

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
CLI_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_repo"
JsonDict = dict[str, Any]


def _run(
    args: list[str], repo_path: Path = CLI_FIXTURE, *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(SRC_ROOT)
    )
    return subprocess.run(
        [sys.executable, "-m", "repogpt.app.cli", *args, str(repo_path)],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
        env=env,
    )


def _write_mcp_mixed_fixture(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "ignored").mkdir()

    (root / "src" / "service.py").write_text(
        "def helper() -> str:\n    return 'service'\n\n"
        "class Demo:\n    def helper(self) -> str:\n        return 'method'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_service.py").write_text(
        "def test_helper() -> None:\n    assert helper() == 'service'\n",
        encoding="utf-8",
    )
    (root / "docs" / "guide.md").write_text(
        "# Title\n"
        "## Details\n"
        "Intro\n"
        "## Details\n"
        "More\n"
        "### Subheading\n"
        "### Subheading\n"
        "### Details\n"
        "# Footer\n",
        encoding="utf-8",
    )
    (root / "ignored" / "skip.py").write_text(
        "def ignored() -> None:\n    return None\n",
        encoding="utf-8",
    )
    (root / ".repogptignore").write_text("ignored/\n", encoding="utf-8")


def _json_lines(stdout: str) -> list[JsonDict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _read_json(path: Path) -> JsonDict:
    return cast(JsonDict, json.loads(path.read_text(encoding="utf-8")))


def _extract_content_text(response: JsonDict) -> JsonDict:
    result = cast(JsonDict, response["result"])
    content = cast(list[JsonDict], result["content"])
    return cast(JsonDict, json.loads(cast(str, content[0]["text"])))


def _assert_payloads_equivalent(
    cli_payload: JsonDict,
    mcp_payload: JsonDict,
) -> None:
    assert cli_payload["schema_version"] == mcp_payload["schema_version"]
    assert cli_payload["kind"] == mcp_payload["kind"]
    assert cli_payload["stats"] == mcp_payload["stats"]
    assert cli_payload["documents"] == mcp_payload["documents"]


def test_mcp_initialize_and_list_tools() -> None:
    initialize = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialize["result"]["serverInfo"]["name"] == "repogpt"
    assert initialize["result"]["serverInfo"]["version"] == repogpt.__version__
    assert repogpt.__version__

    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listed["result"]["tools"]}
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


def test_mcp_language_filter_matches_cli_normalization() -> None:
    cli_run = _run(["--stdout", "--format", "json", "--languages", "py"], CLI_FIXTURE)
    assert cli_run.returncode == 2
    cli_payload = json.loads(cli_run.stdout)

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_ast",
                "arguments": {
                    "repo_path": str(CLI_FIXTURE),
                    "languages": [" PY "],
                },
            },
        }
    )

    payload = _extract_content_text(response)
    assert payload["exit_code"] == 2
    assert payload["artifact"] == cli_payload


def test_mcp_rejects_unsupported_language_like_cli() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_ast",
                "arguments": {
                    "repo_path": str(CLI_FIXTURE),
                    "languages": ["ts"],
                },
            },
        }
    )

    assert response["error"]["code"] == -32000
    assert "unsupported languages: ts; supported: md, py" == response["error"]["message"]


def test_mcp_empty_language_filter_collects_nothing() -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_ast",
                "arguments": {
                    "repo_path": str(CLI_FIXTURE),
                    "languages": [],
                },
            },
        }
    )

    payload = _extract_content_text(response)
    assert payload["exit_code"] == 0
    assert payload["artifact"]["stats"]["total_files"] == 0
    assert payload["artifact"]["records"] == []


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


def test_mcp_end_to_end_mixed_repo_matches_cli_across_flags(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_mcp_mixed_fixture(repo_root)
    resolved_repo_root = repo_root.resolve()

    for include_tests in (False, True):
        include_tests_arg = ["--include-tests"] if include_tests else []
        cli_run = _run(
            ["--stdout", "--format", "json", "--emit", "code-units", *include_tests_arg],
            resolved_repo_root,
            cwd=tmp_path,
        )
        assert cli_run.returncode == 0
        cli_payload = json.loads(cli_run.stdout)

        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "repogpt_emit_code_units",
                    "arguments": {
                        "repo_path": str(resolved_repo_root),
                        "include_tests": include_tests,
                    },
                },
            }
        )

        mcp_payload_response = _extract_content_text(response)
        assert mcp_payload_response["exit_code"] == 0
        mcp_payload = cast(JsonDict, mcp_payload_response["artifact"])
        _assert_payloads_equivalent(cli_payload, mcp_payload)

        cli_ast = _run(
            ["--stdout", "--format", "ndjson", "--flatten", "file", *include_tests_arg],
            resolved_repo_root,
            cwd=tmp_path,
        )
        assert cli_ast.returncode == 0
        cli_records = _json_lines(cli_ast.stdout)
        assert cli_records[-1]["record_type"] == "summary"
        assert cli_records[-1]["schema_version"] == "1"

        response_ast = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "repogpt_emit_ast",
                    "arguments": {
                        "repo_path": str(resolved_repo_root),
                        "format": "ndjson",
                        "flatten": "file",
                        "include_tests": include_tests,
                    },
                },
            }
        )
        mcp_ast_payload = _extract_content_text(response_ast)
        assert mcp_ast_payload["exit_code"] == 0
        mcp_ast = cast(list[JsonDict], mcp_ast_payload["artifact"])
        assert mcp_ast[-1]["record_type"] == "summary"
        assert mcp_ast[-1]["schema_version"] == "1"

    artifact = _run(
        ["--stdout", "--format", "json", "--emit", "code-units", "--include-tests"],
        resolved_repo_root,
        cwd=tmp_path,
    )
    artifact_json = json.loads(artifact.stdout)
    comparison_input = tmp_path / "code_units.json"
    comparison_input.write_text(
        json.dumps(artifact_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    compare = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "repogpt_compare_profiles",
                "arguments": {
                    "artifact_path": str(comparison_input),
                    "query": "helper",
                },
            },
        }
    )

    comparison_payload = _extract_content_text(compare)
    assert comparison_payload["exit_code"] == 0
    comparison = cast(JsonDict, comparison_payload["comparison"])
    assert comparison["query_text"] == "helper"
    assert "flat_rag_v1" in comparison
    assert "structured_rag_v1" in comparison
