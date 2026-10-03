from __future__ import annotations

from pathlib import Path

import pytest

from repogpt.application.exit_codes import exit_code_for_result
from repogpt.domain.analysis import AnalysisRequest
from repogpt.domain.errors import InvalidRepoError
from repogpt.runtime import build_analyze_repo


def test_analyze_repo_returns_projection_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ok.py").write_text("def hello():\n    return 1\n", encoding="utf-8")

    result, projection = build_analyze_repo().run(AnalysisRequest(repo_root=tmp_path))

    payload = projection.json_payload
    assert result.stats.total_files == 1
    assert result.stats.ok_files == 1
    assert result.stopped_early is False
    assert exit_code_for_result(result) == 0
    assert payload["stats"]["ok_files"] == 1
    assert payload["records"][0]["record_type"] == "node"
    assert [path.name for path in tmp_path.iterdir()] == ["ok.py"]
    assert capsys.readouterr().out == ""


def test_analyze_repo_partial_failure_returns_two(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    result, projection = build_analyze_repo().run(
        AnalysisRequest(
            repo_root=tmp_path,
            include_tests=True,
        )
    )

    payload = projection.json_payload
    assert result.stats.total_files == 2
    assert result.stats.failed_files == 1
    assert result.stopped_early is False
    assert exit_code_for_result(result) == 2
    assert payload["stats"]["failed_files"] == 1
    assert payload["failures"][0]["record_type"] == "failure"


def test_parse_error_is_portable_and_has_single_line_breaks(tmp_path: Path) -> None:
    messages = []
    for dirname in ("first", "second"):
        repo = tmp_path / dirname
        repo.mkdir()
        (repo / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        result, _ = build_analyze_repo().run(AnalysisRequest(repo_root=repo))
        failure = result.parsed_files[0].failure
        assert failure is not None
        messages.append(failure.message)

    assert messages[0] == messages[1]
    assert 'File "bad.py", line 1\n    def broken(:' in messages[0]
    assert "\n\n" not in messages[0]
    assert str(tmp_path) not in messages[0]


def test_analyze_repo_fail_fast_returns_partial_projection_and_status_one(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "later.py").write_text("x=1\n", encoding="utf-8")
    result, projection = build_analyze_repo().run(
        AnalysisRequest(
            repo_root=tmp_path,
            fail_fast=True,
        )
    )

    payload = projection.json_payload
    assert result.stopped_early is True
    assert result.stats.total_files == 1
    assert exit_code_for_result(result) == 1
    assert payload["stats"]["total_files"] == 1
    assert payload["failures"][0]["path"] == "bad.py"
    assert payload["records"] == []


def test_analyze_repo_invalid_repo_raises_invalid_repo_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    try:
        build_analyze_repo().run(AnalysisRequest(repo_root=missing))
    except InvalidRepoError as exc:
        assert "does not exist" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("InvalidRepoError not raised")
