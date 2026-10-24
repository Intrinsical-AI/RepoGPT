from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import anyio
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

from repogpt.mcp_server import (
    MAX_RESPONSE_BYTES,
    TOOLS,
    SDKDiagnosticFilter,
    ToolOutcome,
    create_server,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cli_repo"


def _call(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    async def execute() -> types.CallToolResult:
        server = create_server()
        result = await server.request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name=name, arguments=arguments),
            )
        )
        assert isinstance(result.root, types.CallToolResult)
        return result.root

    return anyio.run(execute)


def _payload(result: types.CallToolResult) -> dict[str, Any]:
    assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
    payload = json.loads(result.content[0].text)
    assert payload == result.structuredContent
    assert result.content[0].text == json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return cast(dict[str, Any], payload)


@pytest.mark.parametrize(
    "projection,format", [("ast", "json"), ("ast", "ndjson"), ("code-units", "json")]
)
def test_native_export_matches_cli_bytes_and_verified_receipt(
    tmp_path: Path, projection: str, format: str
) -> None:
    destination = tmp_path / "artifact.json"
    result = _call(
        "repogpt_export",
        {
            "repo_path": str(FIXTURE),
            "projection": projection,
            "format": format,
            "output_path": str(destination),
            "include_tests": True,
        },
    )
    receipt = _payload(result)
    assert result.isError and receipt["complete"] is False
    assert receipt["stats"]["failed_files"] == 1
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "repogpt.app.cli",
            str(FIXTURE),
            "--stdout",
            "--emit",
            projection,
            "--format",
            format,
            "--include-tests",
        ],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        timeout=15,
    )
    assert cli.returncode == 2
    raw = destination.read_bytes()
    assert raw == cli.stdout
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["size_bytes"] == len(raw)
    TOOLS["repogpt_export"].output_validator.validate(receipt)


@pytest.mark.parametrize("projection", ["ast", "code-units"])
@pytest.mark.parametrize("fail_fast", [False, True])
def test_partial_analysis_preserves_native_artifact(
    tmp_path: Path, projection: str, fail_fast: bool
) -> None:
    (tmp_path / "a.py").write_text("def broken(:\n")
    (tmp_path / "b.py").write_text("x = 1\n")
    result = _call(
        "repogpt_analyze",
        {
            "repo_path": str(tmp_path),
            "projection": projection,
            "response_mode": "inline",
            "fail_fast": fail_fast,
        },
    )
    payload = _payload(result)
    assert result.isError and not payload["complete"]
    assert payload["stats"]["failed_files"] == 1
    assert payload["stats"]["ok_files"] == (0 if fail_fast else 1)
    assert payload["artifact"]["failures"] == payload["failures"]
    TOOLS["repogpt_analyze"].output_validator.validate(payload)


def test_analysis_defaults_to_read_only_summary_and_normalizes_extensions(tmp_path: Path) -> None:
    (tmp_path / "café.py").write_text("x = 1\n")
    (tmp_path / "a.md").write_text("# Heading\n")
    before = sorted(tmp_path.iterdir())
    payload = _payload(
        _call("repogpt_analyze", {"repo_path": str(tmp_path), "extensions": [" PY "]})
    )
    assert payload["stats"]["total_files"] == 1 and "artifact" not in payload
    assert payload["complete"]
    assert sorted(tmp_path.iterdir()) == before
    empty = _payload(_call("repogpt_analyze", {"repo_path": str(tmp_path), "extensions": []}))
    assert empty["stats"]["total_files"] == 0


def test_inline_analysis_matches_cli(tmp_path: Path) -> None:
    (tmp_path / "café.py").write_text("def café():\n    return 1\n", encoding="utf-8")
    payload = _payload(
        _call(
            "repogpt_analyze",
            {
                "repo_path": str(tmp_path),
                "response_mode": "inline",
                "projection": "code-units",
                "repo_key": "sample",
            },
        )
    )
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "repogpt.app.cli",
            str(tmp_path),
            "--stdout",
            "--emit",
            "code-units",
            "--repo-key",
            "sample",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert cli.returncode == 0
    assert payload["artifact"] == json.loads(cli.stdout)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"repo_path": " "},
        {"repo_path": "x", "extensions": "py"},
        {"repo_path": "x", "extensions": [1]},
        {"repo_path": "x", "extensions": ["ts"]},
        {"repo_path": "x", "languages": ["py"]},
        {"repo_path": "x", "output_path": "x"},
        {"repo_path": "x", "include_tests": 1},
        {"repo_path": "x", "projection": "other"},
        {"repo_path": "x", "repo_key": "invalid key"},
    ],
)
def test_invalid_analysis_arguments_are_protocol_errors(arguments: dict[str, Any]) -> None:
    with pytest.raises(McpError) as error:
        _call("repogpt_analyze", arguments)
    assert error.value.error.code == -32602


@pytest.mark.parametrize("name", ["repogpt_emit_ast", "repogpt_emit_code_units", "missing"])
def test_removed_and_unknown_tools_have_no_alias(name: str) -> None:
    with pytest.raises(McpError) as error:
        _call(name, {})
    assert error.value.error.code == -32602


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid"])
def test_expected_failure_is_structured(kind: str, tmp_path: Path) -> None:
    target = tmp_path / "input.json"
    if kind == "directory":
        target.mkdir()
    elif kind == "invalid":
        target.write_text("{broken")
    result = _call("repogpt_compare_profiles", {"artifact_path": str(target), "query": "x"})
    assert result.isError
    assert _payload(result)["error"]["code"] == "operation_failed"


def test_comparison_native_parity(tmp_path: Path) -> None:
    from repogpt.utils.retrieval_artifact import load_documents
    from repogpt.utils.retrieval_profiles import compare_profiles

    output = tmp_path / "units.json"
    _call(
        "repogpt_export",
        {"repo_path": str(FIXTURE), "output_path": str(output), "projection": "code-units"},
    )
    result = _call(
        "repogpt_compare_profiles", {"artifact_path": str(output), "query": "sample", "top_k": 2}
    )
    assert not result.isError
    assert _payload(result) == compare_profiles(
        load_documents(output), query_text="sample", top_k=2
    )


@pytest.mark.parametrize("destination", ["-", "/dev/stdout", "/dev/stdin", "/dev/stderr"])
def test_export_requires_regular_destination(destination: str) -> None:
    with pytest.raises(McpError) as error:
        _call("repogpt_export", {"repo_path": str(FIXTURE), "output_path": destination})
    assert error.value.error.code == -32602


@pytest.mark.parametrize("kind", ["source", "symlink", "dangling", "directory", "fifo"])
def test_export_refuses_unsafe_leaf_without_modification(tmp_path: Path, kind: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "source.py"
    source.write_text("x = 1\n")
    destination = repo / "artifact.json"
    if kind == "source":
        destination = source
    elif kind == "symlink":
        destination.symlink_to(source)
    elif kind == "dangling":
        destination.symlink_to(tmp_path / "missing")
    elif kind == "directory":
        destination.mkdir()
    else:
        os.mkfifo(destination)
    with pytest.raises(McpError) as error:
        _call(
            "repogpt_export",
            {"repo_path": str(repo), "output_path": str(destination), "extensions": []},
        )
    assert error.value.error.code == -32602
    assert source.read_text() == "x = 1\n"


def test_export_failure_keeps_previous_file_and_cleans_temporary(tmp_path: Path) -> None:
    output = tmp_path / "artifact.json"
    output.write_bytes(b"previous")
    with patch(
        "repogpt.adapters.writers.artifact_writer.os.replace", side_effect=OSError("injected")
    ):
        result = _call("repogpt_export", {"repo_path": str(FIXTURE), "output_path": str(output)})
    assert result.isError
    assert output.read_bytes() == b"previous"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_replacement_requires_complete_full_selection(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    arguments = {
        "repo_path": str(tmp_path),
        "output_path": str(output),
        "projection": "code-units",
        "replace_scope": True,
    }
    with pytest.raises(McpError) as error:
        _call("repogpt_export", arguments)
    assert error.value.error.code == -32602
    failed = _call("repogpt_export", {**arguments, "include_tests": True})
    assert failed.isError and not output.exists()
    (tmp_path / "source.py").write_text("x = 1\n")
    success = _call("repogpt_export", {**arguments, "include_tests": True})
    assert not success.isError
    assert json.loads(output.read_text())["replace_scope"] is True


def test_inline_response_limit_returns_explicit_error_without_partial_artifact(
    tmp_path: Path,
) -> None:
    (tmp_path / "big.py").write_text('"""' + "x" * 200_000 + '"""\n')
    result = _call("repogpt_analyze", {"repo_path": str(tmp_path), "response_mode": "inline"})
    assert result.isError
    assert _payload(result)["error"]["code"] == "response_too_large"
    assert len(result.model_dump_json().encode()) < MAX_RESPONSE_BYTES
    assert _payload(_call("repogpt_analyze", {"repo_path": str(tmp_path)}))["complete"]


def test_large_failure_evidence_keeps_export_receipt_and_full_native_artifact(
    tmp_path: Path,
) -> None:
    from repogpt.runtime import build_analyze_repo

    analyzer = build_analyze_repo()
    result, artifact = analyzer.run(analyzer.request(repo_path=str(FIXTURE)))
    artifact.json_payload["failures"][0]["error"] = "failure evidence " * 20_000
    destination = tmp_path / "partial.json"
    with patch("repogpt.mcp_server.build_analyze_repo", return_value=analyzer):
        with patch.object(analyzer, "run", return_value=(result, artifact)):
            response = _call(
                "repogpt_export", {"repo_path": str(FIXTURE), "output_path": str(destination)}
            )
    receipt = _payload(response)
    assert response.isError and receipt["output_path"] == str(destination)
    assert receipt["failure_count"] == 1 and receipt["failures_truncated"]
    assert receipt["failures"] == []
    assert json.loads(destination.read_text())["failures"] == artifact.json_payload["failures"]
    assert len(response.model_dump_json().encode()) < MAX_RESPONSE_BYTES


@pytest.mark.parametrize("failure", ["exception", "value_error", "invalid_output", "nonfinite"])
def test_internal_and_output_failures_are_sanitized(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(**_: Any) -> ToolOutcome:
        if failure == "exception":
            raise RuntimeError("PRIVATE-CONTENT")
        if failure == "value_error":
            raise ValueError("PRIVATE-CONTENT")
        if failure == "nonfinite":
            return ToolOutcome({"error": {"code": "x", "message": float("nan")}})
        return ToolOutcome({"PRIVATE-CONTENT": "x"})

    with patch.dict(TOOLS, {"repogpt_analyze": replace(TOOLS["repogpt_analyze"], handler=broken)}):
        with pytest.raises(McpError) as error:
            _call("repogpt_analyze", {"repo_path": "unused"})
    assert error.value.error.code == -32603
    assert "PRIVATE-CONTENT" not in str(error.value)
    assert "PRIVATE-CONTENT" not in caplog.text


def test_sdk_log_filter_sanitizes_root_records_and_preserves_application_diagnostics() -> None:
    record = logging.LogRecord(
        "root",
        logging.WARNING,
        "/env/site-packages/mcp/shared/session.py",
        1,
        "PRIVATE %s",
        ("DATA",),
        None,
    )
    record.exc_text = "PRIVATE trace"
    record.stack_info = "PRIVATE stack"
    assert SDKDiagnosticFilter().filter(record)
    assert "PRIVATE" not in logging.Formatter().format(record)
    app = logging.LogRecord(
        "repogpt", logging.INFO, __file__, 1, "safe event %s", ("complete",), None
    )
    SDKDiagnosticFilter().filter(app)
    assert app.getMessage() == "safe event complete"


def test_worker_keeps_slot_until_cancelled_work_finishes() -> None:
    started = threading.Event()
    release = threading.Event()
    seen: list[int] = []

    def blocking(**_: Any) -> ToolOutcome:
        seen.append(1)
        started.set()
        release.wait(5)
        return ToolOutcome({"error": {"code": "fixture", "message": "done"}})

    async def execute() -> None:
        server = create_server()

        async def invoke(*, task_status: Any = anyio.TASK_STATUS_IGNORED) -> None:
            with anyio.CancelScope() as scope:
                task_status.started(scope)
                await server.request_handlers[types.CallToolRequest](
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="repogpt_analyze", arguments={"repo_path": "unused"}
                        ),
                    )
                )

        async with anyio.create_task_group() as group:
            scope = await group.start(invoke)
            await anyio.to_thread.run_sync(started.wait)
            scope.cancel()
            group.start_soon(invoke)
            await anyio.sleep(0.05)
            assert len(seen) == 1
            release.set()
        assert len(seen) == 2

    with patch.dict(
        TOOLS, {"repogpt_analyze": replace(TOOLS["repogpt_analyze"], handler=blocking)}
    ):
        anyio.run(execute)


def test_installed_style_stdio_session_and_notifications(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("def sample():\n    return 1\n")
    output = tmp_path / "must-not-exist.json"

    async def execute() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "repogpt.mcp_server"],
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                initialized = await session.initialize()
                assert initialized.protocolVersion == "2025-11-25"
                assert initialized.serverInfo.name == "repogpt"
                await session.send_ping()
                listed = await session.list_tools()
                assert {tool.name for tool in listed.tools} == set(TOOLS)
                for tool in listed.tools:
                    assert tool.outputSchema is not None
                    Draft202012Validator.check_schema(tool.outputSchema)
                    assert tool.annotations is not None
                    assert tool.annotations.readOnlyHint == (tool.name != "repogpt_export")
                # Invalid request-only notifications must never execute their tools.
                from mcp.shared.message import SessionMessage

                await writer.send(
                    SessionMessage(
                        types.JSONRPCMessage.model_validate(
                            {
                                "jsonrpc": "2.0",
                                "method": "tools/call",
                                "params": {
                                    "name": "repogpt_export",
                                    "arguments": {
                                        "repo_path": str(tmp_path),
                                        "output_path": str(output),
                                    },
                                },
                            }
                        )
                    )
                )
                await session.send_ping()
                assert not output.exists()
                with pytest.raises(McpError) as error:
                    await session.call_tool(
                        "repogpt_analyze", {"repo_path": str(tmp_path), "languages": []}
                    )
                assert error.value.error.code == -32602
                result = await session.call_tool(
                    "repogpt_analyze", {"repo_path": str(tmp_path), "response_mode": "inline"}
                )
                assert not result.isError and _payload(result)["complete"]
                missing = await session.call_tool(
                    "repogpt_analyze", {"repo_path": str(tmp_path / "absent")}
                )
                assert missing.isError
                await session.send_ping()

    anyio.run(execute)
