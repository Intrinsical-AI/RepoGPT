from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pathspec

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
    (tmp_path / ".repogptignore").write_text("*.py\n__pycache__/\ngenerated/\n", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "ignored.py").write_text("print('ignored')", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "skip.py").write_text("print('no')", encoding="utf-8")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert files == []
    assert sorted(item.relative_path for item in skipped) == [
        ".repogptignore",
        "keep.py",
        "skip.py",
    ]
    assert "generated/ignored.py" not in {item.relative_path for item in skipped}


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

    assert skipped == []


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


def test_collect_handles_invalid_repogptignore_pattern_without_failing(tmp_path: Path) -> None:
    (tmp_path / ".repogptignore").write_text("[invalid\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "skip.py").write_text("print('no')", encoding="utf-8")

    collector = DefaultCollector()

    def raise_pattern_error(*args: object, **kwargs: object) -> pathspec.GitIgnoreSpec:
        _ = args, kwargs
        raise ValueError("invalid pattern")

    with patch.object(pathspec.GitIgnoreSpec, "from_lines", raise_pattern_error):
        files, skipped = collector.collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert {item.relative_path for item in files} == {"keep.py", "skip.py"}
    assert {item.relative_path for item in skipped} == {".repogptignore"}


def test_collect_treats_ambiguous_binary_without_null_as_text(tmp_path: Path) -> None:
    (tmp_path / "ambiguous.py").write_bytes(b"\xff\xfe\xfd" + b"x = 1")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert any(item.relative_path == "ambiguous.py" for item in files)
    assert {item.relative_path for item in skipped} == set()


def test_collect_skips_symlinks_by_default(tmp_path: Path) -> None:
    (tmp_path / "real.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "link_to_real.py").symlink_to("real.py")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert any(item.relative_path == "real.py" for item in files)
    assert any(
        item.relative_path == "link_to_real.py" and item.reason == "symlink" for item in skipped
    )


def test_collect_handles_long_relative_paths_in_output(tmp_path: Path) -> None:
    nested = tmp_path
    for _ in range(3):
        nested = nested / ("nested_" + "x" * 40)
        nested.mkdir()
    (nested / ("module_" + "y" * 120 + ".py")).write_text("x = 1", encoding="utf-8")

    files, skipped = DefaultCollector().collect(AnalysisRequest(repo_root=tmp_path), {"py"})

    assert len(skipped) == 0
    assert len(files) == 1
    assert files[0].relative_path.endswith("module_" + "y" * 120 + ".py")


def test_collect_on_large_synthetic_repo_stable_order_and_test_filter(tmp_path: Path) -> None:
    for index in range(180):
        suffix = "py" if index % 2 == 0 else "md"
        if index % 11 == 0:
            folder = "tests"
            name = f"module_{index:03d}.{'py' if index % 4 == 0 else 'md'}"
        elif index % 7 == 0:
            folder = "package"
            name = f"test_{index:03d}." + suffix
        else:
            folder = f"pkg_{index % 13}"
            name = f"file_{index:03d}." + suffix

        path = tmp_path / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"value = {index}", encoding="utf-8")

    expected_all = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file() and path.suffix.lstrip(".").lower() in {"py", "md"}
    )

    expected_without_tests = [
        item
        for item in expected_all
        if not item.startswith("tests/") and not Path(item).name.startswith(("test_", "test-"))
    ]
    expected_with_tests = [
        item for item in expected_all if item.endswith(".py") or item.endswith(".md")
    ]

    files_default, skipped_default = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=False),
        {"py", "md"},
    )
    files_include_tests, skipped_include = DefaultCollector().collect(
        AnalysisRequest(repo_root=tmp_path, include_tests=True),
        {"py", "md"},
    )

    assert [item.relative_path for item in files_default] == expected_without_tests
    assert [item.relative_path for item in files_include_tests] == expected_with_tests
    assert skipped_default
    assert any(item.reason == "tests_excluded" for item in skipped_default)
    assert not skipped_include
