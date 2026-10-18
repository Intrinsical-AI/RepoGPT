from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

import repogpt
from repogpt.mcp_server import handle_request as dispatch_request

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
CLI_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_repo"
JsonDict = dict[str, Any]


def handle_request(request: JsonDict) -> JsonDict:
    response = dispatch_request(request)
    assert response is not None
    return response


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


def _extract_content_text(response: JsonDict) -> Any:
    result = response["result"]
    assert set(result) == {"content", "structuredContent", "isError"}
    payload = json.loads(result["content"][0]["text"])
    assert result["structuredContent"] == payload
    assert isinstance(payload, dict)
    return payload


def _call_tool(name: str, arguments: JsonDict) -> JsonDict:
    return handle_request(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


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


@pytest.mark.parametrize("requested", ["2025-06-18", "2024-11-05", "2099-01-01"])
def test_mcp_negotiates_only_supported_protocol_version(requested: str) -> None:
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": requested},
        }
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_ping_returns_empty_result() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": "health", "method": "ping"})
    assert response == {"jsonrpc": "2.0", "id": "health", "result": {}}


def test_mcp_text_artifact_is_compact_utf8_json(tmp_path: Path) -> None:
    (tmp_path / "café.py").write_text("def café():\n    return 1\n", encoding="utf-8")
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "repogpt_emit_ast",
                "arguments": {"repo_path": str(tmp_path)},
            },
        }
    )
    text = response["result"]["content"][0]["text"]
    assert "café" in text
    assert text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


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
    assert response["result"]["isError"] is True
    assert payload == cli_payload


@pytest.mark.parametrize("tool_name", ["repogpt_emit_ast", "repogpt_emit_code_units"])
@pytest.mark.parametrize("fail_fast", [False, True])
def test_mcp_parse_failures_mark_retained_artifact_as_error(
    tmp_path: Path, tool_name: str, fail_fast: bool
) -> None:
    (tmp_path / "a_broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "b_good.py").write_text("x = 1\n", encoding="utf-8")
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {"repo_path": str(tmp_path), "fail_fast": fail_fast},
            },
        }
    )

    assert "error" not in response
    assert response["result"]["isError"] is True
    payload = _extract_content_text(response)
    assert payload["stats"]["failed_files"] == 1
    assert payload["stats"]["ok_files"] == (0 if fail_fast else 1)


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
    assert response["result"]["isError"] is True
    assert payload == cli_payload


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

    assert response["error"]["code"] == -32602
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
    assert response["result"]["isError"] is False
    assert payload["stats"]["total_files"] == 0
    assert payload["records"] == []


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
    assert set(payload) == {"schema_version", "format", "records"}
    assert payload["schema_version"] == "3"
    assert payload["format"] == "ndjson"
    records = payload["records"]
    assert response["result"]["isError"] is True
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

    comparison = _extract_content_text(response)
    assert response["result"]["isError"] is False
    assert comparison["query_text"] == "helper"
    assert "flat_rag_v3" in comparison
    assert "structured_rag_v3" in comparison
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

        mcp_payload = _extract_content_text(response)
        assert response["result"]["isError"] is False
        _assert_payloads_equivalent(cli_payload, mcp_payload)

        cli_ast = _run(
            ["--stdout", "--format", "ndjson", "--flatten", "file", *include_tests_arg],
            resolved_repo_root,
            cwd=tmp_path,
        )
        assert cli_ast.returncode == 0
        cli_records = _json_lines(cli_ast.stdout)
        assert cli_records[-1]["record_type"] == "summary"
        assert cli_records[-1]["schema_version"] == "3"

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
        mcp_ast = _extract_content_text(response_ast)["records"]
        assert response_ast["result"]["isError"] is False
        assert mcp_ast == cli_records
        assert mcp_ast[-1]["record_type"] == "summary"
        assert mcp_ast[-1]["schema_version"] == "3"

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

    comparison = _extract_content_text(compare)
    assert compare["result"]["isError"] is False
    assert comparison["query_text"] == "helper"
    assert "flat_rag_v3" in comparison
    assert "structured_rag_v3" in comparison


@pytest.mark.parametrize("top_k", [0, 1, 7])
def test_mcp_compare_profiles_exposes_top_k(tmp_path: Path, top_k: int) -> None:
    artifact = tmp_path / "units.json"
    generated = _run(["--emit", "code-units", "-o", str(artifact)])
    assert generated.returncode == 2

    response = _call_tool(
        "repogpt_compare_profiles",
        {"artifact_path": str(artifact), "query": "helper", "top_k": top_k},
    )
    payload = _extract_content_text(response)
    assert response["result"]["isError"] is False
    assert payload["top_k"] == top_k
    assert payload["flat_rag_v3"]["seed_count"] <= top_k
    if top_k == 0:
        assert payload["flat_rag_v3"]["external_ids"] == []
        assert payload["structured_rag_v3"]["external_ids"] == []


@pytest.mark.parametrize("invalid", [-1, True, False, 1.0, "1", None])
def test_mcp_invalid_top_k_is_rejected_before_artifact_read(invalid: Any) -> None:
    with patch("repogpt.mcp_server.load_documents") as load:
        response = _call_tool(
            "repogpt_compare_profiles",
            {"artifact_path": "missing.json", "query": "helper", "top_k": invalid},
        )
        load.assert_not_called()
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "tool_name,format,schema_version",
    [
        ("repogpt_emit_ast", "json", "3"),
        ("repogpt_emit_ast", "ndjson", "3"),
        ("repogpt_emit_code_units", "json", "6"),
    ],
)
@pytest.mark.parametrize("failure_mode", ["none", "partial", "fail-fast"])
def test_mcp_file_output_returns_only_verified_receipt(
    tmp_path: Path, tool_name: str, format: str, schema_version: str, failure_mode: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "z_café.py").write_text("def café():\n    return '🙂'\n", encoding="utf-8")
    if failure_mode != "none":
        (repo / "a_broken.py").write_text("def broken(:\n", encoding="utf-8")
    output = tmp_path / "artifact.json"
    output.write_bytes(b"previous artifact")
    output.chmod(0o640)
    arguments: JsonDict = {
        "repo_path": str(repo),
        "output_path": str(output),
        "fail_fast": failure_mode == "fail-fast",
    }
    if tool_name == "repogpt_emit_ast":
        arguments["format"] = format

    response = _call_tool(tool_name, arguments)
    receipt = _extract_content_text(response)
    raw = output.read_bytes()
    assert set(receipt) == {
        "output_path",
        "format",
        "schema_version",
        "size_bytes",
        "sha256",
        "stats",
    }
    assert receipt["output_path"] == str(output)
    assert receipt["format"] == format
    assert receipt["schema_version"] == schema_version
    assert receipt["size_bytes"] == len(raw)
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert output.stat().st_mode & 0o777 == 0o640
    assert response["result"]["isError"] is (failure_mode != "none")
    if format == "ndjson":
        stats = json.loads(raw.splitlines()[-1])["stats"]
    else:
        stats = json.loads(raw)["stats"]
    assert receipt["stats"] == stats
    assert stats["failed_files"] == (failure_mode != "none")
    assert stats["ok_files"] == (0 if failure_mode == "fail-fast" else 1)
    assert list(tmp_path.glob(".*.tmp")) == []


def test_mcp_file_receipt_resolves_parent_and_retains_leaf(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    destination = tmp_path / "actual"
    destination.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)
    response = _call_tool(
        "repogpt_emit_ast",
        {"repo_path": str(repo), "output_path": str(alias / "artifact.json")},
    )

    receipt = _extract_content_text(response)
    assert receipt["output_path"] == str(destination / "artifact.json")
    assert (destination / "artifact.json").is_file()


@pytest.mark.parametrize("destination", ["", " \t ", "-", "/dev/stdout", "/dev/fd/1", "/dev/null"])
def test_mcp_rejects_blank_and_stdio_output_paths_before_analysis(destination: str) -> None:
    with patch("repogpt.mcp_server.build_analyze_repo") as build:
        response = _call_tool(
            "repogpt_emit_ast", {"repo_path": "unused", "output_path": destination}
        )
        build.assert_not_called()
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink", "directory", "fifo", "source"])
def test_mcp_file_output_refuses_unsafe_leaf_without_modification(
    tmp_path: Path, kind: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "sample.py"
    original = b"x = 1\n"
    source.write_bytes(original)
    output = tmp_path / "out.json"
    if kind == "symlink":
        output.symlink_to(source)
    elif kind == "dangling-symlink":
        output.symlink_to(tmp_path / "missing")
    elif kind == "directory":
        output.mkdir()
    elif kind == "fifo":
        os.mkfifo(output)
    else:
        output = source

    response = _call_tool("repogpt_emit_ast", {"repo_path": str(repo), "output_path": str(output)})
    assert response["error"]["code"] == -32602
    assert source.read_bytes() == original
    if "symlink" in kind:
        assert output.is_symlink()


def test_mcp_file_output_does_not_create_missing_parent(tmp_path: Path) -> None:
    output = tmp_path / "missing" / "out.json"
    response = _call_tool(
        "repogpt_emit_ast", {"repo_path": str(tmp_path), "output_path": str(output)}
    )
    assert response["result"]["isError"] is True
    assert set(_extract_content_text(response)) == {"error"}
    assert not output.parent.exists()


def test_mcp_file_output_refuses_source_after_fail_fast_stop(tmp_path: Path) -> None:
    (tmp_path / "a_broken.py").write_text("def broken(:\n", encoding="utf-8")
    source = tmp_path / "z_later.py"
    source.write_bytes(b"x = 1\n")

    response = _call_tool(
        "repogpt_emit_ast",
        {"repo_path": str(tmp_path), "output_path": str(source), "fail_fast": True},
    )

    assert response["error"]["code"] == -32602
    assert source.read_bytes() == b"x = 1\n"


def test_mcp_file_write_failure_preserves_previous_file_and_request_recovery(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous artifact")
    with patch("repogpt.adapters.writers.artifact_writer.os.replace", side_effect=OSError("disk")):
        failed = _call_tool(
            "repogpt_emit_ast", {"repo_path": str(tmp_path), "output_path": str(output)}
        )

    assert failed["result"]["isError"] is True
    assert "failed to write artifact" in _extract_content_text(failed)["error"]
    assert output.read_bytes() == b"previous artifact"
    assert list(tmp_path.glob(".*.tmp")) == []
    recovered = _call_tool("repogpt_emit_ast", {"repo_path": str(tmp_path)})
    assert recovered["result"]["isError"] is False


@pytest.mark.parametrize(
    "tool_name,format",
    [
        ("repogpt_emit_ast", "json"),
        ("repogpt_emit_ast", "ndjson"),
        ("repogpt_emit_code_units", "json"),
    ],
)
@pytest.mark.parametrize("mode", ["inline", "file", "partial", "failure"])
def test_mcp_declared_output_schema_validates_all_result_modes(
    tmp_path: Path, tool_name: str, format: str, mode: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sample.py").write_text("x = 1\n", encoding="utf-8")
    if mode == "partial":
        (repo / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    arguments: JsonDict = {"repo_path": str(repo if mode != "failure" else repo / "missing")}
    if tool_name == "repogpt_emit_ast":
        arguments["format"] = format
    if mode == "file":
        arguments["output_path"] = str(tmp_path / "out.json")
    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool = next(item for item in listed["result"]["tools"] if item["name"] == tool_name)
    assert tool["annotations"]["readOnlyHint"] is False
    assert tool["annotations"]["destructiveHint"] is True
    schema = tool["outputSchema"]
    Draft202012Validator.check_schema(schema)
    response = _call_tool(tool_name, arguments)
    payload = _extract_content_text(response)
    validator = Draft202012Validator(schema)
    validator.validate(payload)
    assert not validator.is_valid({**payload, "unknown_result_field": True})


def test_mcp_compare_output_schema_covers_success_and_error(tmp_path: Path) -> None:
    artifact = tmp_path / "units.json"
    _run(["--emit", "code-units", "-o", str(artifact)])
    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool = next(
        item for item in listed["result"]["tools"] if item["name"] == "repogpt_compare_profiles"
    )
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["inputSchema"]["properties"]["top_k"] == {
        "type": "integer",
        "minimum": 0,
        "default": 3,
    }
    validator = Draft202012Validator(tool["outputSchema"])
    for path in (artifact, tmp_path / "missing.json"):
        response = _call_tool(
            "repogpt_compare_profiles", {"artifact_path": str(path), "query": "helper"}
        )
        payload = _extract_content_text(response)
        validator.validate(payload)
        assert not validator.is_valid({**payload, "unknown_result_field": True})
