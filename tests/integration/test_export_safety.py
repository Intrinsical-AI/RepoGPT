from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.app.cli import main
from repogpt.domain.analysis import (
    AnalysisRequest,
    AstProjection,
    CodeUnitsProjection,
)
from repogpt.domain.errors import CollectionFailure, InvalidRequestError, UnsafeReplacementError
from repogpt.mcp_server import handle_request
from repogpt.runtime import build_analyze_repo


def _export(root: Path, output: Path, **options: Any) -> dict[str, Any]:
    request = AnalysisRequest(
        repo_root=root,
        projection="code_units",
        **options,
    )
    _, projection = build_analyze_repo().run(request)
    ArtifactWriter().write(projection, output, format=request.format)
    return cast(dict[str, Any], json.loads(output.read_text(encoding="utf-8")))


def test_repository_identity_is_canonical_and_explicit_key_is_portable(tmp_path: Path) -> None:
    roots = [tmp_path / name / "same" for name in ("a", "b")]
    output = tmp_path / "output.json"
    for root in roots:
        root.mkdir(parents=True)
        (root / "sample.py").write_text("def f(): return 1\n", encoding="utf-8")
    first = _export(roots[0], output)
    second = _export(roots[1], output)
    canonical = os.path.normcase(str(roots[0].resolve()))
    assert first["repo_key"] == "local-" + hashlib.sha256(os.fsencode(canonical)).hexdigest()
    assert first["repo_key"] != second["repo_key"]
    alias = tmp_path / "alias"
    alias.symlink_to(roots[0], target_is_directory=True)
    assert _export(alias, output) == first
    portable = _export(roots[0], output, repo_key="shared.project-1")
    assert _export(roots[1], output, repo_key="shared.project-1") == portable
    assert portable["scope"] == "repogpt:shared.project-1"
    assert portable["replace_scope"] is False


@pytest.mark.parametrize("key", ["", "A", "a b", "../repo", "é", "a:b", "x" * 129, "x\n"])
def test_invalid_repo_key_fails_before_collection(tmp_path: Path, key: str) -> None:
    with patch("repogpt.adapters.fs.collector.DefaultCollector.collect") as collect:
        with pytest.raises(InvalidRequestError, match="repo_key"):
            _export(tmp_path, tmp_path / "out.json", repo_key=key)
        collect.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        {"include_tests": False},
        {"include_tests": True, "supported_languages": []},
        {"include_tests": True, "supported_languages": ["py"]},
    ],
)
def test_replacement_rejects_incomplete_selectors_before_analysis(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    with patch("repogpt.adapters.fs.collector.DefaultCollector.collect") as collect:
        with pytest.raises(InvalidRequestError):
            _export(tmp_path, tmp_path / "out.json", replace_scope=True, **options)
        collect.assert_not_called()


@pytest.mark.parametrize("case", ["empty", "syntax", "decode", "large", "binary", "fail_fast"])
def test_incomplete_replacement_preserves_existing_artifact(tmp_path: Path, case: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "output.json"
    output.write_bytes(b"previous artifact")
    if case != "empty":
        (root / "good.py").write_text("def f(): pass\n", encoding="utf-8")
    if case in {"syntax", "fail_fast"}:
        (root / "bad.py").write_bytes(b"def broken(:\n")
    if case == "decode":
        (root / "bad.py").write_bytes(b'x = "\xff"\n')
    if case == "large":
        (root / "large.py").write_bytes(b"#" + b"x" * 100)
    if case == "binary":
        (root / "binary.py").write_bytes(b"\0")
    with pytest.raises(UnsafeReplacementError):
        _export(
            root,
            output,
            include_tests=True,
            replace_scope=True,
            max_file_size=50,
            fail_fast=case == "fail_fast",
        )
    assert output.read_bytes() == b"previous artifact"
    partial = _export(root, output, include_tests=True, max_file_size=50)
    assert partial["replace_scope"] is False


def test_complete_replacement_respects_known_ignores(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".repogptignore").write_text("private/\n", encoding="utf-8")
    (root / "private").mkdir()
    (root / "private" / "broken.py").write_bytes(b"def broken(:\n")
    (root / "test_sample.py").write_text("def test_f(): pass\n", encoding="utf-8")
    (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
    payload = _export(
        root,
        tmp_path / "out.json",
        include_tests=True,
        supported_languages=["md", "py"],
        replace_scope=True,
    )
    assert payload["replace_scope"] is True
    assert {doc["path"] for doc in payload["documents"]} == {"test_sample.py", "guide.md"}


@pytest.mark.parametrize("stage", ["walk", "stat", "probe", "load", "ignore"])
def test_read_failure_aborts_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    sample = root / "sample.py"
    sample.write_text("x = 1\n", encoding="utf-8")
    output = tmp_path / "out.json"
    output.write_bytes(b"previous")
    if stage == "walk":

        def fail_walk(*args: Any, **kwargs: Any) -> None:
            kwargs["onerror"](PermissionError(13, "denied", str(root / "locked")))

        monkeypatch.setattr("repogpt.adapters.fs.collector.os.walk", fail_walk)
    elif stage == "stat":
        original_stat = Path.stat

        def fail_stat(path: Path, **kwargs: Any) -> os.stat_result:
            if path == sample:
                raise FileNotFoundError("candidate vanished")
            return original_stat(path, **kwargs)

        monkeypatch.setattr(Path, "stat", fail_stat)
    elif stage == "probe":

        def fail_probe(path: Path) -> bool:
            raise PermissionError("cannot probe")

        monkeypatch.setattr("repogpt.adapters.fs.collector.is_likely_binary", fail_probe)
    elif stage == "load":

        def fail_read(path: Path) -> bytes:
            raise PermissionError("cannot load")

        monkeypatch.setattr(Path, "read_bytes", fail_read)
    else:
        (root / ".repogptignore").mkdir()
    with pytest.raises(CollectionFailure):
        _export(root, output)
    assert output.read_text(encoding="utf-8") == "previous"


@pytest.mark.parametrize("format", ["json", "ndjson"])
def test_atomic_writer_preserves_artifact_and_cleans_temp_on_failure(
    tmp_path: Path, format: Any
) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous")
    projection = AstProjection(
        {
            "schema_version": "2",
            "repo_root": ".",
            "stats": {},
            "failures": [],
            "records": [{"ok": True}, {"bad": object()}] if format == "ndjson" else [],
        }
    )
    if format == "json":
        with (
            patch(
                "repogpt.adapters.writers.artifact_writer.os.replace", side_effect=OSError("disk")
            ),
            pytest.raises(OSError),
        ):
            ArtifactWriter().write(projection, output, format=format)
    else:
        with pytest.raises(TypeError):
            ArtifactWriter().write(projection, output, format=format)
    assert output.read_bytes() == b"previous"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["out.json"]


def test_atomic_writer_keeps_existing_permissions(tmp_path: Path) -> None:
    output = tmp_path / "out.json"
    output.write_bytes(b"previous")
    output.chmod(0o640)
    ArtifactWriter().write(
        CodeUnitsProjection({"documents": []}),
        output,
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert json.loads(output.read_text(encoding="utf-8")) == {"documents": []}


@pytest.mark.parametrize("kind", ["internal", "external"])
def test_residual_identity_collision_aborts_before_writing(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.py").write_text("def a(): pass\ndef b(): pass\n", encoding="utf-8")
    output = tmp_path / "out.json"
    output.write_bytes(b"previous")
    if kind == "internal":
        with (
            patch("repogpt.utils.node_utils.stable_node_id", return_value="same"),
            pytest.raises(ValueError, match="Duplicate AST"),
        ):
            _export(root, output)
    else:
        from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector

        original = CodeUnitsProjector._identities

        def collide(
            self: CodeUnitsProjector, **kwargs: Any
        ) -> tuple[dict[str, str], dict[str, str]]:
            identities, names = original(self, **kwargs)
            return dict.fromkeys(identities, "same"), names

        with (
            patch.object(CodeUnitsProjector, "_identities", collide),
            pytest.raises(ValueError, match="Duplicate external"),
        ):
            _export(root, output)
    assert output.read_bytes() == b"previous"


def test_cli_and_mcp_distinguish_invalid_selection_and_unsafe_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["repogpt", str(tmp_path), "--emit", "code-units", "--replace-scope", "--stdout"],
    )
    with pytest.raises(SystemExit) as invalid:
        main()
    assert invalid.value.code == 2
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--include-tests"])
    assert main() == 3
    for include_tests in (False, True):
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": "keep",
                "method": "tools/call",
                "params": {
                    "name": "repogpt_emit_code_units",
                    "arguments": {
                        "repo_path": str(tmp_path),
                        "include_tests": include_tests,
                        "replace_scope": True,
                    },
                },
            }
        )
        assert response is not None
        assert response["id"] == "keep"
        if include_tests:
            assert response["result"]["isError"] is True
            assert "complete, non-empty" in response["result"]["content"][0]["text"]
        else:
            assert response["error"]["code"] == -32602
