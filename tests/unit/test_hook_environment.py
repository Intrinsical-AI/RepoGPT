from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Make hook recipes require a POSIX shell"
)


def _tools(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is required to exercise the hook recipes")
    log = tmp_path / "requests.jsonl"
    uv = tmp_path / "uv"
    uv.write_text(
        f"#!{sys.executable} -B\n"
        "import json,os,subprocess,sys\n"
        "args=sys.argv[1:]\n"
        "row={'argv':args,'source_selector':os.environ.get('UV_PROJECT_ENVIRONMENT')}\n"
        "fd=os.open(os.environ['HOOK_TEST_LOG'],os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)\n"
        "os.write(fd,(json.dumps(row)+'\\n').encode()); os.close(fd)\n"
        "if '-c' in args:\n"
        "    index=args.index('-c')\n"
        "    raise SystemExit(subprocess.run("
        "[sys.executable,'-I','-B','-c',*args[index+1:]],check=False).returncode)\n"
        "if 'pre_commit' in args and args[-2:]==['run','--all-files']:\n"
        "    raise SystemExit(subprocess.run("
        "[os.environ['HOOK_TEST_MAKE'],'type'],check=False).returncode)\n"
        "# Every other request is recorded only: no real sync, hook install or source tool runs.\n"
    )
    uv.chmod(0o700)
    environment = {
        "PATH": str(tmp_path) + os.pathsep + str(Path(make).parent) + os.pathsep + os.defpath,
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOOK_TEST_LOG": str(log),
        "HOOK_TEST_MAKE": make,
    }
    return Path(make), uv, environment


def _run(
    make: Path,
    uv: Path,
    environment: dict[str, str],
    source: Path,
    hooks: Path,
    *targets: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(make),
            *targets,
            "UV=" + str(uv),
            "HOOK_ENV=" + str(hooks),
            # A caller cannot replace the snapshot used to guard the actual source environment.
            "DEV_UV_PROJECT_ENVIRONMENT=" + str(source.parent / "wrong-cli-override"),
        ],
        cwd=ROOT,
        env={**environment, "UV_PROJECT_ENVIRONMENT": str(source)},
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _requests(environment: dict[str, str]) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in Path(environment["HOOK_TEST_LOG"]).read_text().splitlines()
    ]


@pytest.mark.parametrize("layout", ("distinct", "equal", "alias", "nested", "parent"))
def test_hook_sync_refuses_source_aliases_before_requesting_exact_sync(
    tmp_path: Path, layout: str
) -> None:
    make, uv, environment = _tools(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    marker = source / "preserved"
    marker.write_bytes(b"source environment must remain unchanged")
    hooks = tmp_path / "hooks"
    if layout == "equal":
        hooks = source
    elif layout == "alias":
        hooks.symlink_to(source)
    elif layout == "nested":
        hooks = source / "nested"
    elif layout == "parent":
        hooks = tmp_path
    result = _run(make, uv, environment, source, hooks, "sync-hooks")
    rows = _requests(environment)
    syncs = [row for row in rows if row["argv"][0] == "sync"]
    if layout == "distinct":
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(syncs) == 1
        assert syncs[0]["source_selector"] == str(hooks)
        assert syncs[0]["argv"] == ["sync", "--locked", "--only-group", "hooks", "--python", "3.12"]
        assert not hooks.exists()
    else:
        assert result.returncode != 0
        assert "HOOK_ENV must be separate" in result.stderr
        assert not syncs
    assert marker.read_bytes() == b"source environment must remain unchanged"


def test_stable_hook_install_precedes_source_sync_and_preserves_nested_selector(
    tmp_path: Path,
) -> None:
    # Bind the fake nested route to the actual configured system hook.
    make_entries = [
        line.strip()
        for line in (ROOT / ".pre-commit-config.yaml").read_text().splitlines()
        if line.strip().startswith("entry: make ")
    ]
    assert make_entries == ["entry: make type"]
    make, uv, environment = _tools(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    hooks = tmp_path / "hooks-not-created"
    result = _run(make, uv, environment, source, hooks, "-j4", "validate")
    assert result.returncode == 0, result.stdout + result.stderr
    rows = _requests(environment)
    hook_commands = [(index, row) for index, row in enumerate(rows) if "pre_commit" in row["argv"]]
    install = next(
        index for index, row in hook_commands if row["argv"][-2:] == ["install", "--install-hooks"]
    )
    run = next(index for index, row in hook_commands if row["argv"][-2:] == ["run", "--all-files"])
    source_syncs = [
        index
        for index, row in enumerate(rows)
        if row["argv"][0] == "sync" and "--group" in row["argv"]
    ]
    assert source_syncs and install < source_syncs[0] < run
    assert all(index > install for index in source_syncs)
    assert any(index > run and "mypy" in row["argv"] for index, row in enumerate(rows)), (
        "system hook must invoke nested make type"
    )
    for _, row in hook_commands:
        assert row["argv"][:6] == [
            "run",
            "--no-project",
            "--no-sync",
            "--python",
            str(hooks / "bin/python"),
            "python",
        ]
        assert row["source_selector"] == str(source)
    assert all(rows[index]["source_selector"] == str(source) for index in source_syncs)
    assert not hooks.exists(), "fake tools must never create an environment"
