from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repogpt.mcp_server import handle_request

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_notification_never_dispatches_a_request_tool() -> None:
    with patch("repogpt.mcp_server.build_analyze_repo") as build:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "repogpt_emit_code_units",
                    "arguments": {"repo_path": "unused"},
                },
            }
        )
        assert response is None
        build.assert_not_called()


def test_importing_mcp_does_not_configure_logging() -> None:
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging, structlog; before = structlog.get_config().copy(); "
            "handlers = list(logging.getLogger().handlers); "
            "import repogpt.mcp_server; "
            "assert structlog.get_config() == before; "
            "assert logging.getLogger().handlers == handlers",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPO_ROOT,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "" and run.stderr == ""


def _session(lines: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "repogpt.mcp_server"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )


def _call(
    arguments: dict[str, Any], req_id: int = 2, *, tool_name: str = "repogpt_emit_code_units"
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )


def test_stdio_initialization_notifications_and_recovery(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    run = _session(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
            ),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 9}}
            ),
            "{broken",
            _call({"repo_path": str(tmp_path)}),
        ]
    )
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert run.returncode == 0
    assert [response["id"] for response in responses] == [1, None, 2]
    assert responses[1]["error"]["code"] == -32700
    assert responses[2]["result"]["isError"] is False
    payload = json.loads(responses[2]["result"]["content"][0]["text"])
    assert len(payload["documents"]) == 1


def test_stdio_recovers_after_oversized_numeric_json_id() -> None:
    run = _session(
        [
            '{"jsonrpc":"2.0","id":' + "9" * 5000 + ',"method":"initialize"}',
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
    )
    assert run.returncode == 0, run.stderr
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert responses[0]["id"] is None
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 2
    assert "tools" in responses[1]["result"]


def test_stdio_logs_remain_on_stderr_during_collection_failure(tmp_path: Path) -> None:
    (tmp_path / ".repogptignore").write_bytes(b"private/\n\xff")
    (tmp_path / "sample.py").write_text("x = 1\n", encoding="utf-8")
    run = _session(
        [
            _call({"repo_path": str(tmp_path)}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}),
        ]
    )
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert run.returncode == 0
    assert [response["id"] for response in responses] == [2, 3]
    assert "error" not in responses[0]
    assert responses[0]["result"]["isError"] is True
    assert "repogptignore" in responses[0]["result"]["content"][0]["text"]
    assert "repogptignore" in run.stderr
    assert "tools" in responses[1]["result"]


@pytest.mark.parametrize(
    "case", ["missing_repo", "refused_replacement", "missing_input", "bad_input"]
)
def test_tool_execution_errors_preserve_stdio_session(tmp_path: Path, case: str) -> None:
    good_repo = tmp_path / "good"
    good_repo.mkdir()
    (good_repo / "sample.py").write_text("x = 1\n", encoding="utf-8")
    tool_name = "repogpt_emit_code_units"
    arguments: dict[str, Any]
    if case == "missing_repo":
        arguments = {"repo_path": str(tmp_path / "missing")}
        expected_error = "does not exist"
    elif case == "refused_replacement":
        empty_repo = tmp_path / "empty"
        empty_repo.mkdir()
        arguments = {
            "repo_path": str(empty_repo),
            "include_tests": True,
            "replace_scope": True,
        }
        expected_error = "replace_scope requires"
    else:
        artifact = tmp_path / "input.json"
        if case == "bad_input":
            artifact.write_text("{broken", encoding="utf-8")
        tool_name = "repogpt_compare_profiles"
        arguments = {"artifact_path": str(artifact), "query": "sample"}
        expected_error = "Expecting property name" if case == "bad_input" else "input.json"

    run = _session(
        [
            _call(arguments, tool_name=tool_name),
            _call({"repo_path": str(good_repo)}, req_id=3),
        ]
    )
    responses = [json.loads(line) for line in run.stdout.splitlines()]
    assert run.returncode == 0, run.stderr
    assert [response["id"] for response in responses] == [2, 3]
    failed, recovered = responses
    assert "error" not in failed
    assert failed["result"]["isError"] is True
    assert expected_error in failed["result"]["content"][0]["text"]
    assert recovered["result"]["isError"] is False
    payload = json.loads(recovered["result"]["content"][0]["text"])
    assert {document["path"] for document in payload["documents"]} == {"sample.py"}


@pytest.mark.parametrize("invalid", ["false", 0, 1, None, [], {}])
def test_mcp_rejects_non_boolean_arguments(tmp_path: Path, invalid: Any) -> None:
    run = _session([_call({"repo_path": str(tmp_path), "include_tests": invalid})])
    response = json.loads(run.stdout)
    assert response["id"] == 2
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"repo_path": 1},
        {"repo_path": "unused", "languages": "py"},
        {"repo_path": "unused", "languages": [1]},
        {"repo_path": "unused", "languages": None},
        {"repo_path": "unused", "unknown": True},
        {"repo_path": "unused", "languages": ["ts"]},
    ],
)
def test_mcp_rejects_invalid_tool_arguments(arguments: dict[str, Any]) -> None:
    response = json.loads(_session([_call(arguments)]).stdout)
    assert response["id"] == 2
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize("field,value", [("flatten", "nested"), ("format", "yaml")])
def test_mcp_rejects_invalid_ast_layout_before_analysis(field: str, value: str) -> None:
    request = json.loads(_call({"repo_path": "unused", field: value}, tool_name="repogpt_emit_ast"))
    with patch("repogpt.mcp_server.build_analyze_repo") as build:
        response = handle_request(request)
        build.assert_not_called()
    assert response is not None
    assert response["id"] == 2
    assert response["error"]["code"] == -32602


@pytest.mark.parametrize(
    "incoming",
    [
        None,
        [],
        "text",
        {},
        {"jsonrpc": "1.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": 1, "params": "bar"},
        {"jsonrpc": "1.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": True, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": None, "method": "tools/list"},
    ],
)
def test_mcp_invalid_envelope_is_not_a_json_parse_error(incoming: Any) -> None:
    response = json.loads(_session([json.dumps(incoming)]).stdout)
    assert response["error"]["code"] == -32600


def test_mcp_unknown_method_and_invalid_params_preserve_id() -> None:
    responses = [
        json.loads(line)
        for line in _session(
            [
                json.dumps({"jsonrpc": "2.0", "id": "unknown", "method": "missing"}),
                json.dumps(
                    {"jsonrpc": "2.0", "id": "params", "method": "tools/call", "params": []}
                ),
                json.dumps(
                    {"jsonrpc": "2.0", "id": "name", "method": "tools/call", "params": {"name": []}}
                ),
            ]
        ).stdout.splitlines()
    ]
    assert [(response["id"], response["error"]["code"]) for response in responses] == [
        ("unknown", -32601),
        ("params", -32602),
        ("name", -32602),
    ]


@pytest.mark.parametrize("key", ["", "UPPER", "a b", "../repo", "x" * 129, "x\n"])
def test_mcp_repo_key_validation_precedes_collection(key: str) -> None:
    request = json.loads(_call({"repo_path": "unused", "repo_key": key}))
    with patch("repogpt.adapters.fs.collector.DefaultCollector.collect") as collect:
        response = handle_request(request)
        collect.assert_not_called()
    assert response is not None
    assert response["error"]["code"] == -32602
