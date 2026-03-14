from pathlib import Path
import pytest

from repogpt.adapters.collector.simple_collector import (
    SimpleCollector,
    ignore_reason,
    should_ignore,
)
from repogpt.models import AnalysisConf


def test_collect_ignores_git_files(tmp_path: Path) -> None:
    # Preparo un repo con .git, .gitignore y archivos .py / .pyc
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("test")
    (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__/\n")
    (tmp_path / "main.py").write_text("print('test')")
    (tmp_path / "test.pyc").write_text("test")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "test.pyc").write_text("test")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path)
    result = collector.collect(conf)

    assert len(result.files) == 1
    assert result.files[0].name == "main.py"


def test_collect_respects_repogptignore(tmp_path: Path) -> None:
    # Ahora usamos .repogptignore en lugar de argumentos al constructor
    (tmp_path / ".repogptignore").write_text("*.py\n__pycache__/\n")
    (tmp_path / "keep.py").write_text("print('ok')")
    (tmp_path / "skip.py").write_text("print('no')")
    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path)
    result = collector.collect(conf)

    assert len(result.files) == 0


def test_collect_includes_tests_when_requested(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x=1")
    (tmp_path / "test_foo.py").write_text("x=2")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path, include_tests=True)
    result = collector.collect(conf)

    names = {f.name for f in result.files}
    assert names == {"foo.py", "test_foo.py"}


def test_collect_excludes_tests_by_default(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text("x=1")
    (tmp_path / "test_foo.py").write_text("x=2")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path, include_tests=False)
    result = collector.collect(conf)

    names = {f.name for f in result.files}
    assert names == {"foo.py"}


def test_collect_empty_directory_returns_empty(tmp_path: Path) -> None:
    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path)
    result = collector.collect(conf)
    assert result.files == []


def test_collect_nonexistent_directory_raises(tmp_path: Path) -> None:
    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=Path("no-such-dir"))
    with pytest.raises(FileNotFoundError):
        collector.collect(conf)


def test_collect_file_instead_of_directory_raises(tmp_path: Path) -> None:
    file = tmp_path / "solo.py"
    file.write_text("x=1")
    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=file)
    with pytest.raises(NotADirectoryError):
        collector.collect(conf)


def test_collect_includes_supported_hidden_paths_by_default(tmp_path: Path) -> None:
    hidden_dir = tmp_path / ".github"
    hidden_dir.mkdir()
    (hidden_dir / "workflow.py").write_text("x=1", encoding="utf-8")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path, include_tests=True)
    result = collector.collect(conf)

    assert [path.relative_to(tmp_path).as_posix() for path in result.files] == [
        ".github/workflow.py"
    ]


def test_collect_returns_files_in_stable_relative_path_order(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("x=1", encoding="utf-8")
    nested = tmp_path / "a"
    nested.mkdir()
    (nested / "a.py").write_text("x=2", encoding="utf-8")
    (tmp_path / "a.py").write_text("x=3", encoding="utf-8")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path, include_tests=True)
    result = collector.collect(conf)

    assert [path.relative_to(tmp_path).as_posix() for path in result.files] == [
        "a.py",
        "a/a.py",
        "b.py",
    ]


def test_collect_with_empty_languages_returns_no_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "b.md").write_text("# hi\n", encoding="utf-8")

    collector = SimpleCollector()
    result = collector.collect(
        AnalysisConf(repo_path=tmp_path, include_tests=True, languages=[])
    )

    assert result.files == []
    assert sorted(path.name for path in result.skipped) == ["a.py", "b.md"]


def test_collect_skipped_does_not_include_ignored_directories(tmp_path: Path) -> None:
    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    (ignored_dir / "config").write_text("test", encoding="utf-8")

    collector = SimpleCollector()
    result = collector.collect(AnalysisConf(repo_path=tmp_path, include_tests=True))

    assert all(path.is_file() for path in result.skipped)


def test_ignore_reason_reports_why_a_path_is_skipped(tmp_path: Path) -> None:
    ignored_dir = tmp_path / ".git"
    ignored_dir.mkdir()
    ignored_file = ignored_dir / "config"
    ignored_file.write_text("test", encoding="utf-8")

    assert ignore_reason(ignored_file, tmp_path) == "default_ignore"
    assert should_ignore(ignored_file, tmp_path) is True
