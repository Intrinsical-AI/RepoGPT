from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _closed_output(
    command: list[str], *, after_prefix: bool, incoming: bytes | None = None
) -> tuple[int, bytes]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    if not after_prefix:
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            run = subprocess.run(
                command,
                input=incoming,
                stdout=write_fd,
                stderr=subprocess.PIPE,
                env=env,
                timeout=15,
            )
        finally:
            os.close(write_fd)
        return run.returncode, run.stderr

    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE if incoming is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        bufsize=0,
    ) as process:
        if incoming is not None:
            assert process.stdin is not None
            process.stdin.write(incoming)
            process.stdin.close()
            process.stdin = None
        assert process.stdout is not None
        assert process.stdout.read(200)
        process.stdout.close()
        process.stdout = None
        _, stderr = process.communicate(timeout=15)
        return process.returncode, stderr


@pytest.mark.parametrize("after_prefix", [False, True], ids=["buffered", "during-write"])
@pytest.mark.parametrize(
    "options",
    [[], ["--format", "ndjson"], ["--emit", "code-units"]],
    ids=["ast-json", "ast-ndjson", "code-units"],
)
def test_cli_closed_stdout_exits_cleanly(
    tmp_path: Path, options: list[str], after_prefix: bool
) -> None:
    if after_prefix:
        (tmp_path / "sample.py").write_text(
            'def sample():\n    """' + "x" * 100_000 + '"""\n    pass\n', encoding="utf-8"
        )
    code, stderr = _closed_output(
        [sys.executable, "-m", "repogpt.app.cli", str(tmp_path), "--stdout", *options],
        after_prefix=after_prefix,
    )
    assert code == 0, stderr.decode()
    assert b"BrokenPipe" not in stderr
    assert b"Traceback" not in stderr
    assert b"Exception ignored" not in stderr
    assert b"[error" not in stderr


@pytest.mark.parametrize("after_prefix", [False, True], ids=["buffered", "during-write"])
def test_mcp_closed_stdout_exits_cleanly(tmp_path: Path, after_prefix: bool) -> None:
    (tmp_path / "sample.py").write_text(
        'def sample():\n    """' + "x" * (100_000 if after_prefix else 1) + '"""\n',
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "repogpt_emit_code_units", "arguments": {"repo_path": str(tmp_path)}},
    }
    code, stderr = _closed_output(
        [sys.executable, "-m", "repogpt.mcp_server"],
        after_prefix=after_prefix,
        incoming=(json.dumps(request) + "\n").encode(),
    )
    assert code == 0, stderr.decode()
    assert b"BrokenPipe" not in stderr
    assert b"Traceback" not in stderr
    assert b"Exception ignored" not in stderr


@pytest.mark.parametrize("entrypoint", ["cli", "mcp"])
def test_other_stdout_io_errors_keep_exit_code_3(tmp_path: Path, entrypoint: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    destination = tmp_path / "readonly-output"
    destination.write_bytes(b"previous")
    command = [sys.executable, "-m", "repogpt.app.cli", str(root), "--stdout"]
    incoming = None
    if entrypoint == "mcp":
        command = [sys.executable, "-m", "repogpt.mcp_server"]
        incoming = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    with destination.open("rb") as readonly_stdout:
        run = subprocess.run(
            command,
            input=incoming,
            stdout=readonly_stdout,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
            timeout=15,
        )
    assert run.returncode == 3, run.stderr
    assert run.stderr.count("I/O error") == 1
    assert "Traceback" not in run.stderr
    assert "Exception ignored" not in run.stderr
    assert destination.read_bytes() == b"previous"


@pytest.mark.parametrize("stage", ["missing-parent", "permission", "replace"])
def test_cli_write_failure_has_one_diagnostic_and_preserves_destination(
    tmp_path: Path, stage: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.py").write_text("x = 1\n", encoding="utf-8")
    output = (
        tmp_path / "missing" / "out.json" if stage == "missing-parent" else tmp_path / "out.json"
    )
    command = [sys.executable, "-m", "repogpt.app.cli"]
    if stage != "missing-parent":
        output.write_bytes(b"previous artifact")
        target = "tempfile.NamedTemporaryFile" if stage == "permission" else "os.replace"
        error = errno.EACCES if stage == "permission" else errno.EIO
        script = (
            "from unittest.mock import patch\n"
            "from repogpt.app.cli import main\n"
            f"with patch('repogpt.adapters.writers.artifact_writer.{target}', "
            f"side_effect=OSError({error}, 'injected write failure')):\n"
            "    raise SystemExit(main())\n"
        )
        command = [sys.executable, "-c", script]
    run = subprocess.run(
        [*command, str(root), "-o", str(output)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        timeout=15,
    )
    assert run.returncode == 3
    assert run.stdout == ""
    errors = [line for line in run.stderr.splitlines() if "[error" in line]
    assert len(errors) == 1, run.stderr
    assert "output I/O error" in errors[0]
    assert str(output) in errors[0]
    assert "unexpected error" not in run.stderr
    assert "Traceback" not in run.stderr
    assert list(tmp_path.glob(".*.tmp")) == []
    if stage != "missing-parent":
        assert output.read_bytes() == b"previous artifact"
    else:
        assert not output.exists()
