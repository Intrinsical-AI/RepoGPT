"""Accept exact wheel/sdist bytes in fresh environments, recording provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(
            f"{command[0]} failed ({result.returncode})\n{result.stdout}{result.stderr}"
        )
    return result.stdout


def source_receipt(env: dict[str, str]) -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return run(["git", "--no-optional-locks", *arguments], cwd=ROOT, env=env).strip()

    revision = git("rev-parse", "HEAD")
    if env.get("CI_SOURCE_SHA"):
        assert revision == env["CI_SOURCE_SHA"], "CI checked out a different source revision"
        assert not git("status", "--porcelain", "--untracked-files=normal"), "CI source is dirty"
    paths = [
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "Makefile",
        ROOT / ".pre-commit-config.yaml",
        ROOT / ".github/workflows/ci.yml",
        ROOT / "scripts/smoke_package.py",
        ROOT / "scripts/probe_installed.py",
    ]
    paths.extend(
        path
        for path in (ROOT / "src/repogpt").rglob("*")
        if path.is_file() and (path.suffix in {".py", ".json"} or path.name == "py.typed")
    )
    return {
        "revision": revision,
        "tree": git("rev-parse", "HEAD^{tree}"),
        "checkout_path": str(ROOT.resolve()),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
        "files": {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(paths)},
        "github": {
            key: env[key]
            for key in (
                "GITHUB_REPOSITORY",
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_SHA",
                "GITHUB_WORKFLOW_REF",
                "GITHUB_WORKFLOW_SHA",
            )
            if key in env
        },
    }


def wheel_files(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if name.startswith("repogpt/") and not name.endswith("/")
        }


def wheel_metadata(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {
            name.split(".dist-info/", 1)[1]: hashlib.sha256(archive.read(name)).hexdigest()
            for name in archive.namelist()
            if ".dist-info/" in name and name.endswith(("/METADATA", "/entry_points.txt"))
        }


def check_packaged_documents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        description = archive.read(metadata_path).split(b"\n\n", 1)[1].decode("utf-8")
        assert description.rstrip("\n") == (ROOT / "README.md").read_text(encoding="utf-8").rstrip(
            "\n"
        )
        license_path = next(
            name for name in archive.namelist() if name.endswith("/licenses/LICENSE")
        )
        assert archive.read(license_path) == (ROOT / "LICENSE").read_bytes()


def smoke(dist: Path, output: Path, work_root: Path | None = None) -> dict[str, Any]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    env["PYTHONSAFEPATH"] = "1"
    uv = shutil.which("uv")
    assert uv is not None, "uv is required"
    wheels, sdists = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1, "Expected exactly one wheel and one sdist"
    wheel, sdist = wheels[0], sdists[0]
    source = source_receipt(env)
    expected = {
        path.removeprefix("src/"): digest
        for path, digest in source["files"].items()
        if path.startswith("src/")
    }
    assert wheel_files(wheel) == expected, "Wheel package differs from source files"
    check_packaged_documents(wheel)
    artifacts = {
        path.name: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
        for path in (wheel, sdist)
    }
    (output / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {name}\n" for name, item in artifacts.items())
    )
    version = run([uv, "version", "--short"], cwd=ROOT, env=env).strip()
    receipt: dict[str, Any] = {
        "source": source,
        "artifacts": artifacts,
        "installed": {},
        "python": sys.version,
        "uv": run([uv, "--version"], cwd=ROOT, env=env).strip(),
    }
    scratch_root = (work_root or Path(env.get("RUNNER_TEMP") or tempfile.gettempdir())).resolve()
    assert not scratch_root.is_relative_to(ROOT.resolve()), (
        "Package scratch root must be outside the checkout"
    )
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="repogpt-package-", dir=scratch_root) as temporary:
        work = Path(temporary).resolve()
        assert not work.is_relative_to(ROOT.resolve()), (
            "Package scratch must be outside the checkout"
        )
        receipt["scratch"] = {
            "root": str(scratch_root),
            "path": str(work),
            "outside_checkout": True,
        }
        probe = work / "probe_installed.py"
        shutil.copyfile(ROOT / "scripts/probe_installed.py", probe)
        constraints = work / "constraints.txt"
        run(
            [
                uv,
                "export",
                "--frozen",
                "--extra",
                "mcp",
                "--no-dev",
                "--no-emit-project",
                "--no-hashes",
                "--output-file",
                str(constraints),
            ],
            cwd=ROOT,
            env=env,
        )
        rebuilt = work / "rebuilt"
        run([uv, "build", "--wheel", "--out-dir", str(rebuilt), str(sdist)], cwd=work, env=env)
        rebuilt_wheels = list(rebuilt.glob("*.whl"))
        assert len(rebuilt_wheels) == 1
        assert wheel_files(rebuilt_wheels[0]) == expected, (
            "Sdist rebuild differs from source package"
        )
        assert wheel_metadata(rebuilt_wheels[0]) == wheel_metadata(wheel), (
            "Sdist metadata differs from the original wheel"
        )
        receipt["sdist_rebuilt_wheel"] = {
            "name": rebuilt_wheels[0].name,
            "sha256": sha256(rebuilt_wheels[0]),
        }
        for name, artifact in (("wheel", wheel), ("sdist", rebuilt_wheels[0])):
            environment = work / f"venv-{name}"
            run([uv, "venv", "--python", sys.executable, str(environment)], cwd=work, env=env)
            python = environment / "bin/python"
            run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--constraint",
                    str(constraints),
                    str(artifact),
                ],
                cwd=work,
                env=env,
            )
            base_work = work / f"probe-{name}-base"
            base_work.mkdir()
            base_output = base_work / "receipt.json"
            run(
                [
                    str(python),
                    "-I",
                    str(probe),
                    str(artifact),
                    str(base_output),
                    "--expected-version",
                    version,
                    "--base",
                ],
                cwd=base_work,
                env=env,
            )
            receipt["installed"][f"{name}_base"] = json.loads(base_output.read_text())
            run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--constraint",
                    str(constraints),
                    f"{artifact}[mcp]",
                ],
                cwd=work,
                env=env,
            )
            probe_work = work / f"probe-{name}"
            probe_work.mkdir()
            probe_output = probe_work / "receipt.json"
            run(
                [
                    str(python),
                    "-I",
                    str(probe),
                    str(artifact),
                    str(probe_output),
                    "--expected-version",
                    version,
                ],
                cwd=probe_work,
                env=env,
            )
            receipt["installed"][name] = json.loads(probe_output.read_text())
    assert not work.exists(), "Temporary installed environments were not removed"
    receipt["cleanup"] = {
        "temporary_environments_removed": True,
        "fixtures_removed": True,
        "scratch_removed": True,
    }
    assert all(sha256(dist / name) == item["sha256"] for name, item in artifacts.items())
    receipt["status"] = "passed"
    return receipt


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt-dir", type=Path, default=ROOT / "dist/package-evidence")
    parser.add_argument(
        "--work-root",
        type=Path,
        help="External scratch parent; defaults to RUNNER_TEMP or the system temporary directory",
    )
    arguments = parser.parse_args()
    output = arguments.receipt_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    suite = ET.Element("testsuite", name="installed-package", tests="1", failures="0")
    case = ET.SubElement(
        suite, "testcase", name="exact-wheel-and-sdist", classname="repogpt.package"
    )
    started = time.monotonic()
    try:
        receipt = smoke(arguments.dist_dir.resolve(), output, arguments.work_root)
    except Exception as exc:
        # A CLI acceptance runner must retain failures, including subprocess/probe errors.
        suite.set("failures", "1")
        ET.SubElement(case, "failure", message=type(exc).__name__).text = str(exc)
        (output / "receipt.json").write_text(
            json.dumps({"status": "failed", "error": str(exc)}, indent=2) + "\n"
        )
        raise
    else:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        LOGGER.info("Installed wheel and sdist acceptance passed: %s", output / "receipt.json")
    finally:
        case.set("time", f"{time.monotonic() - started:.3f}")
        ET.ElementTree(suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    main()
