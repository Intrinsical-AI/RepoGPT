from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from repogpt.adapters.fs.collector import DefaultCollector, ignore_reason, should_ignore
from repogpt.domain.analysis import AnalysisRequest


def test_collect_ignores_git_files(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("test", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")
    (tmp_path / "test.pyc").write_text("test", encoding="utf-8")

    files, _ = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py", "md"})

    assert [collected.relative_path for collected in files] == ["main.py"]


def test_collect_respects_repogptignore(tmp_path: Path) -> None:
    (tmp_path / ".repogptignore").write_text("*.py\n__pycache__/\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "skip.py").write_text("print('no')", encoding="utf-8")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert files == []
    assert sorted(item.relative_path for item in skipped) == [
        ".repogptignore",
        "keep.py",
        "skip.py",
    ]


def test_collect_includes_tests_when_requested(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "test_foo.py").write_text("x=2", encoding="utf-8")

    files, _ = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=True),
        {"py"},
    )

    assert {collected.relative_path for collected in files} == {"foo.py", "test_foo.py"}


def test_collect_excludes_tests_by_default(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "test_foo.py").write_text("x=2", encoding="utf-8")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert {collected.relative_path for collected in files} == {"foo.py"}
    assert {item.relative_path for item in skipped} == {"test_foo.py"}


def test_collect_returns_files_in_stable_relative_path_order(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("x=1", encoding="utf-8")
    nested = tmp_path / "a"
    nested.mkdir()
    (nested / "a.py").write_text("x=2", encoding="utf-8")
    (tmp_path / "a.py").write_text("x=3", encoding="utf-8")

    files, _ = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=True),
        {"py"},
    )

    assert [collected.relative_path for collected in files] == ["a.py", "a/a.py", "b.py"]


def test_collect_with_empty_languages_returns_no_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "b.md").write_text("# hi\n", encoding="utf-8")

    files, skipped = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=True),
        set(),
    )

    assert files == []
    assert sorted(item.relative_path for item in skipped) == ["a.py", "b.md"]


def test_collect_skipped_does_not_include_ignored_directories(tmp_path: Path) -> None:
    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    (ignored_dir / "config").write_text("test", encoding="utf-8")

    _, skipped = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=True),
        {"py"},
    )

    assert all(item.abs_path.is_file() for item in skipped)


def test_ignore_reason_reports_why_a_path_is_skipped(tmp_path: Path) -> None:
    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    ignored_file = ignored_dir / "config"
    ignored_file.write_text("test", encoding="utf-8")

    assert ignore_reason(ignored_file, tmp_path) == "default_ignore"
    assert should_ignore(ignored_file, tmp_path) is True


def test_collect_excludes_tests_uses_relative_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "tests" / "myproject"
    repo_root.mkdir(parents=True)
    (repo_root / "src.py").write_text("x=1", encoding="utf-8")
    (repo_root / "test_src.py").write_text("x=2", encoding="utf-8")
    inner_tests = repo_root / "tests"
    inner_tests.mkdir()
    (inner_tests / "conftest.py").write_text("x=3", encoding="utf-8")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=repo_root), {"py"})

    assert {item.relative_path for item in files} == {"src.py"}
    assert {item.relative_path for item in skipped} == {"test_src.py", "tests/conftest.py"}


def test_collect_skips_file_that_disappears_during_stat(tmp_path: Path) -> None:
    (tmp_path / "stable.py").write_text("x=1", encoding="utf-8")
    vanishing = tmp_path / "vanishing.py"
    vanishing.write_text("x=2", encoding="utf-8")

    original_stat = Path.stat
    call_counts: dict[str, int] = {}

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self.name == "vanishing.py" and follow_symlinks:
            call_counts[str(self)] = call_counts.get(str(self), 0) + 1
            if call_counts[str(self)] >= 1:
                raise OSError("file vanished")
        return original_stat(self, follow_symlinks=follow_symlinks)

    with patch.object(Path, "stat", flaky_stat):
        files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert len(files) == 1
    assert files[0].relative_path == "stable.py"
    assert any(item.relative_path == "vanishing.py" for item in skipped)
