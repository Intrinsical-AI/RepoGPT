from __future__ import annotations

import hashlib
import importlib
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from mcp import types

from repogpt.app import cli
from repogpt.mcp_server import create_server
from repogpt.runtime import build_analyze_repo


def _export(repo: Path, destination: Path) -> types.CallToolResult:
    async def execute() -> types.CallToolResult:
        result = await create_server().request_handlers[types.CallToolRequest](
            types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(
                    name="repogpt_export",
                    arguments={"repo_path": str(repo), "output_path": str(destination)},
                ),
            )
        )
        assert isinstance(result.root, types.CallToolResult)
        return result.root

    return anyio.run(execute)


def test_oversized_export_keeps_a_verified_publication_receipt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "broken.py").write_text("def broken(:\n")
    destination = tmp_path / "artifact.json"
    limit = 750 + 2 * len(str(destination).encode("utf-8"))
    with patch("repogpt.mcp_server.MAX_RESPONSE_BYTES", limit):
        result = _export(repo, destination)
    payload = result.structuredContent
    assert payload is not None and payload["output_path"] == str(destination)
    assert result.isError and payload["details_truncated"] is True
    assert payload["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert payload["size_bytes"] == destination.stat().st_size
    assert json.loads(result.content[0].model_dump()["text"]) == payload
    assert len(result.model_dump_json(by_alias=True, exclude_none=True).encode()) <= limit


def test_unrepresentable_export_receipt_refuses_before_publication(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("x = 1\n")
    destination = tmp_path / "artifact.json"
    destination.write_bytes(b"previous artifact")
    with patch("repogpt.mcp_server.MAX_RESPONSE_BYTES", 450):
        result = _export(repo, destination)
    assert result.isError
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "response_too_large"
    assert destination.read_bytes() == b"previous artifact"
    assert not list(tmp_path.glob(".artifact.json.*.tmp"))


def test_cli_checks_destination_before_analysis(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.py").write_text("x = 1\n")
    analyzer = build_analyze_repo()
    with (
        patch("sys.argv", ["repogpt", str(repo), "-o", str(tmp_path / "missing" / "out.json")]),
        patch.object(cli, "build_analyze_repo", return_value=analyzer),
        patch.object(analyzer, "run", wraps=analyzer.run) as run,
    ):
        assert cli.main() == 3
    run.assert_not_called()


def test_mcp_launcher_explains_missing_optional_dependencies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    launcher = importlib.import_module("repogpt.app.mcp_cli")
    with patch.object(launcher, "import_module", side_effect=ModuleNotFoundError(name="anyio")):
        assert launcher.main() == 2
    captured = capsys.readouterr()
    assert "repogpt[mcp]" in captured.err and "Traceback" not in captured.err
    assert captured.out == ""


def test_mcp_launcher_does_not_hide_unrelated_missing_dependencies() -> None:
    launcher = importlib.import_module("repogpt.app.mcp_cli")
    with patch.object(launcher, "import_module", side_effect=ModuleNotFoundError(name="broken")):
        with pytest.raises(ModuleNotFoundError):
            launcher.main()


def test_mcp_startup_suppresses_sdk_info_and_redacts_warnings(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from repogpt import mcp_server

    sdk_logger = logging.getLogger("mcp")
    monkeypatch.setattr(sdk_logger, "level", logging.NOTSET)
    monkeypatch.setattr(mcp_server, "configure_logging", lambda: None)

    def emit(*_: Any) -> None:
        sdk_logger.info("synthetic request")
        sdk_logger.warning("PRIVATE diagnostic")

    monkeypatch.setattr(anyio, "run", emit)
    with caplog.at_level(logging.INFO):
        assert mcp_server.main() == 0
    assert not [record for record in caplog.records if record.levelno == logging.INFO]
    assert "PRIVATE" not in caplog.text and "MCP diagnostic (WARNING)" in caplog.text
