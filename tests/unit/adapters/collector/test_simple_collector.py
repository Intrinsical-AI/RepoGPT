import os
from pathlib import Path
from unittest.mock import patch
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
    result = collector.collect(AnalysisConf(repo_path=tmp_path, include_tests=True, languages=[]))

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


def test_collect_excludes_tests_uses_relative_path(tmp_path: Path) -> None:
    # Repo que vive dentro de un directorio llamado "tests" en el sistema de ficheros.
    # Los archivos internos que NO son de tests deben incluirse igualmente.
    repo_root = tmp_path / "tests" / "myproject"
    repo_root.mkdir(parents=True)
    (repo_root / "src.py").write_text("x=1", encoding="utf-8")
    (repo_root / "test_src.py").write_text("x=2", encoding="utf-8")
    inner_tests = repo_root / "tests"
    inner_tests.mkdir()
    (inner_tests / "conftest.py").write_text("x=3", encoding="utf-8")

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=repo_root, include_tests=False)
    result = collector.collect(conf)

    names = {f.name for f in result.files}
    # src.py incluido; test_src.py y tests/conftest.py excluidos
    assert names == {"src.py"}
    skipped_names = {f.name for f in result.skipped}
    assert "test_src.py" in skipped_names
    assert "conftest.py" in skipped_names


def test_collect_skips_file_that_disappears_during_stat(tmp_path: Path) -> None:
    # Si p.stat() lanza OSError (race condition: archivo borrado entre rglob y stat),
    # el colector debe continuar sin propagar la excepción.
    (tmp_path / "stable.py").write_text("x=1", encoding="utf-8")
    vanishing = tmp_path / "vanishing.py"
    vanishing.write_text("x=2", encoding="utf-8")

    original_stat = Path.stat
    # Cuenta las llamadas stat(follow_symlinks=True) para vanishing.py.
    # La primera la hace is_file() y debe pasar; la segunda la hace
    # nuestro p.stat().st_size explícito y debe fallar.
    call_counts: dict[str, int] = {}

    def flaky_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if self.name == "vanishing.py" and follow_symlinks:
            call_counts[str(self)] = call_counts.get(str(self), 0) + 1
            if call_counts[str(self)] >= 2:
                raise OSError("file vanished")
        return original_stat(self, follow_symlinks=follow_symlinks)

    collector = SimpleCollector()
    conf = AnalysisConf(repo_path=tmp_path)
    with patch.object(Path, "stat", flaky_stat):
        result = collector.collect(conf)

    assert len(result.files) == 1
    assert result.files[0].name == "stable.py"
    assert any(p.name == "vanishing.py" for p in result.skipped)
