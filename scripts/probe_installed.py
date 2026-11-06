"""Probe installed distribution bytes and native interfaces outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import runpy
import socket
import subprocess
import sys
import tempfile
import zipfile
from importlib.resources import files
from pathlib import Path
from typing import Any


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def install_socket_guard() -> dict[str, Any]:
    """Deny Internet sockets/DNS before package imports; allow local loop sockets."""
    denied: list[str] = []

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        internet_socket = event == "socket.__new__" and arguments[1] in {
            socket.AF_INET,
            socket.AF_INET6,
        }
        internet_socket = internet_socket or (
            event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}
            and arguments[0].family in {socket.AF_INET, socket.AF_INET6}
        )
        dns = event in {
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
            "socket.getnameinfo",
        }
        if internet_socket or dns:
            denied.append(event)
            raise PermissionError("Installed acceptance denies Internet sockets and DNS")

    sys.addaudithook(audit)
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            connection = socket.socket(family)
        except PermissionError:
            pass
        else:
            connection.close()
            raise AssertionError("Internet socket guard self-test failed")
    try:
        socket.getaddrinfo("example.invalid", 443)
    except PermissionError:
        pass
    else:
        raise AssertionError("DNS guard self-test failed")
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"local")
        assert right.recv(5) == b"local"
    assert len(denied) == 3
    denied.clear()
    return {
        "self_tests": {
            "ipv4_denied": True,
            "ipv6_denied": True,
            "dns_denied": True,
            "unix_socketpair_allowed": True,
        },
        "denied_operations": denied,
    }


def launcher_command(console: str, audit_output: Path, *arguments: str) -> list[str]:
    return [
        sys.executable,
        "-I",
        str(Path(__file__).resolve()),
        "--launch",
        str(Path(sys.executable).with_name(console)),
        str(audit_output),
        *arguments,
    ]


def guarded_launcher() -> None:
    guard = install_socket_guard()
    console, output = Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    assert console.is_relative_to(Path(sys.prefix).resolve())
    guard["launcher"] = {
        "path": str(console),
        "sha256": digest(console.read_bytes()),
        "arguments": sys.argv[4:],
        "executable": sys.executable,
    }
    sys.argv = [str(console), *sys.argv[4:]]
    try:
        runpy.run_path(str(console), run_name="__main__")
    finally:
        output.write_text(json.dumps(guard, indent=2) + "\n", encoding="utf-8")


def run_cli(*arguments: str) -> bytes:
    descriptor, audit_name = tempfile.mkstemp(prefix="cli-guard-", suffix=".json", dir=Path.cwd())
    os.close(descriptor)
    return subprocess.run(
        launcher_command("repogpt", Path(audit_name), *arguments),
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def installed_files(wheel: Path, expected_version: str) -> dict[str, Any]:
    import repogpt

    distribution = importlib.metadata.distribution("repogpt")
    root = Path(str(files("repogpt"))).resolve()
    assert root.is_relative_to(Path(sys.prefix).resolve()), root
    assert Path(repogpt.__file__).resolve() == root / "__init__.py"
    assert distribution.version == repogpt.__version__ == expected_version
    assert distribution.metadata["Requires-Python"] == ">=3.10"
    assert distribution.metadata.get_all("Provides-Extra") == ["mcp"]
    entrypoints = {entry.name: entry.value for entry in distribution.entry_points}
    assert entrypoints == {
        "repogpt": "repogpt.app.cli:main",
        "repogpt-mcp": "repogpt.app.mcp_cli:main",
    }
    with zipfile.ZipFile(wheel) as archive:
        expected = {
            name: digest(archive.read(name))
            for name in archive.namelist()
            if not name.endswith(("/", "/RECORD"))
        }
    actual = {
        name: digest(Path(str(distribution.locate_file(name))).read_bytes()) for name in expected
    }
    assert expected == actual, "Installed package files differ from the wheel"
    assert {
        str(entry)
        for entry in distribution.files or []
        if str(entry).startswith("repogpt/") and not str(entry).endswith(".pyc")
    } == {name for name in expected if name.startswith("repogpt/")}
    assert {
        "repogpt/py.typed",
        "repogpt/schemas/ast-v3.schema.json",
        "repogpt/schemas/code-units-v6.schema.json",
    } <= actual.keys()
    return {
        "version": distribution.version,
        "origin": str(root),
        "files": actual,
        "entrypoints": entrypoints,
        "python": sys.version,
        "dependencies": {
            item.metadata["Name"]: item.version for item in importlib.metadata.distributions()
        },
    }


def check_base_install() -> None:
    assert importlib.util.find_spec("mcp") is None
    run_cli("--help")
    result = subprocess.run(
        launcher_command("repogpt-mcp", Path.cwd() / "mcp-base-guard.json"),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 2 and b"repogpt[mcp]" in result.stderr
    assert not result.stdout and b"Traceback" not in result.stderr


async def check_native_interfaces(work: Path) -> dict[str, Any]:
    from jsonschema import Draft202012Validator
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client.stdio import stdio_client
    from mcp.shared.exceptions import McpError

    repo = work / "fixture"
    repo.mkdir()
    (repo / "sample.py").write_text(
        "import os\n\nclass Demo:\n    def helper(self, value: int) -> int:\n"
        "        return value + 1\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Demo\n\nA helper example.\n", encoding="utf-8")
    before = {path.name: digest(path.read_bytes()) for path in repo.iterdir()}
    params = StdioServerParameters(
        command=sys.executable,
        args=launcher_command("repogpt-mcp", work / "mcp-guard.json")[1:],
        cwd=str(work),
        env={**os.environ, "PYTHONSAFEPATH": "1"},
    )
    receipts: list[dict[str, Any]] = []
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            assert initialized.protocolVersion == "2025-11-25"
            assert initialized.serverInfo.name == "repogpt"
            await session.send_ping()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert set(tools) == {"repogpt_analyze", "repogpt_export", "repogpt_compare_profiles"}
            for name, tool in tools.items():
                assert tool.annotations is not None and tool.outputSchema is not None
                assert tool.annotations.readOnlyHint == (name != "repogpt_export")
                Draft202012Validator.check_schema(tool.outputSchema)

            def payload(name: str, result: types.CallToolResult) -> dict[str, Any]:
                assert not result.isError and result.structuredContent is not None
                assert len(result.content) == 1 and isinstance(result.content[0], types.TextContent)
                assert json.loads(result.content[0].text) == result.structuredContent
                Draft202012Validator(tools[name].outputSchema).validate(result.structuredContent)
                return result.structuredContent

            summary = payload(
                "repogpt_analyze",
                await session.call_tool("repogpt_analyze", {"repo_path": str(repo)}),
            )
            assert summary["complete"] and summary["schema_version"] == "3"
            assert "artifact" not in summary
            for projection, format in (("ast", "json"), ("ast", "ndjson"), ("code-units", "json")):
                destination = work / f"{projection}.{format}"
                arguments: dict[str, Any] = {
                    "repo_path": str(repo),
                    "projection": projection,
                    "format": format,
                    "output_path": str(destination),
                    "include_tests": True,
                }
                cli_arguments = [
                    str(repo),
                    "--stdout",
                    "--emit",
                    projection,
                    "--format",
                    format,
                    "--include-tests",
                ]
                if projection == "code-units":
                    arguments.update(repo_key="installed-smoke", replace_scope=True)
                    cli_arguments.extend(["--repo-key", "installed-smoke", "--replace-scope"])
                receipt = payload(
                    "repogpt_export", await session.call_tool("repogpt_export", arguments)
                )
                raw = destination.read_bytes()
                assert raw == run_cli(*cli_arguments)
                assert receipt["sha256"] == digest(raw) and receipt["size_bytes"] == len(raw)
                assert receipt["complete"] and receipt["output_path"] == str(destination)
                schema_name = (
                    "ast-v3.schema.json" if projection == "ast" else "code-units-v6.schema.json"
                )
                schema = json.loads(
                    files("repogpt").joinpath("schemas").joinpath(schema_name).read_text()
                )
                validator = Draft202012Validator(schema)
                for item in (
                    [json.loads(line) for line in raw.splitlines()]
                    if format == "ndjson"
                    else [json.loads(raw)]
                ):
                    validator.validate(item)
                receipts.append(receipt)
            comparison = payload(
                "repogpt_compare_profiles",
                await session.call_tool(
                    "repogpt_compare_profiles",
                    {"artifact_path": str(work / "code-units.json"), "query": "helper"},
                ),
            )
            assert comparison
            state_before = {
                path.relative_to(work).as_posix(): digest(path.read_bytes())
                for path in work.rglob("*")
                if path.is_file()
            }
            try:
                await session.call_tool(
                    "repogpt_export",
                    {
                        "repo_path": str(repo),
                        "output_path": str(repo / "sample.py"),
                        "extensions": [],
                    },
                )
            except McpError as exc:
                assert exc.error.code == -32602
            else:
                raise AssertionError("Installed SDK allowed publication over a source file")
            assert state_before == {
                path.relative_to(work).as_posix(): digest(path.read_bytes())
                for path in work.rglob("*")
                if path.is_file()
            }
            await session.send_ping()
    assert before == {path.name: digest(path.read_bytes()) for path in repo.iterdir()}
    return {
        "publication_receipts": receipts,
        "refused_publication": {
            "error_code": -32602,
            "state_unchanged": True,
            "session_recovered": True,
        },
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--launch":
        guarded_launcher()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--base", action="store_true")
    arguments = parser.parse_args()
    guard = install_socket_guard()
    receipt = installed_files(arguments.wheel, arguments.expected_version)
    receipt["profile"] = "base" if arguments.base else "mcp"
    receipt["expectations"] = {
        "mcp_available": not arguments.base,
        "declared_optional_extra": "mcp",
    }
    if arguments.base:
        check_base_install()
    else:
        import anyio

        async def check() -> dict[str, Any]:
            with anyio.fail_after(60):
                return await check_native_interfaces(arguments.output.parent)

        receipt.update(anyio.run(check))
        assert importlib.metadata.version("mcp") == "1.28.1"
        assert importlib.metadata.version("anyio") == "4.14.2"
    assert not guard["denied_operations"]
    receipt["socket_guard"] = guard
    receipt["child_guards"] = [
        json.loads(path.read_text())
        for path in sorted(arguments.output.parent.glob("*guard*.json"))
    ]
    assert receipt["child_guards"] and all(
        not item["denied_operations"] for item in receipt["child_guards"]
    )
    receipt["status"] = "passed"
    arguments.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
