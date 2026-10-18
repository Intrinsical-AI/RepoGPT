from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cleaner(root: Path, *, dist: bool = False) -> None:
    source = Path(__file__).resolve().parents[2] / "scripts" / "clean_artifacts.py"
    destination = root / "scripts" / "clean_artifacts.py"
    destination.parent.mkdir()
    shutil.copyfile(source, destination)
    subprocess.run(
        [sys.executable, str(destination), *(["--dist"] if dist else [])],
        check=True,
        capture_output=True,
    )


def test_distclean_preserves_sources_environments_and_symlink_targets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.pyc").write_text("keep", encoding="utf-8")
    (repo / ".mypy_cache").symlink_to(outside, target_is_directory=True)
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    for name in (".venv", ".git", ".agents"):
        (repo / name).mkdir()
        (repo / name / "keep.pyc").write_text("keep", encoding="utf-8")
    for name in ("build", "dist", ".ruff_cache", ".pytest_cache", "src/x.egg-info"):
        directory = repo / name
        directory.mkdir()
        (directory / "generated").write_text("generated", encoding="utf-8")
    (repo / "src" / "__pycache__").mkdir()
    (repo / "src" / "__pycache__" / "module.pyc").write_bytes(b"cache")

    _run_cleaner(repo, dist=True)

    assert (outside / "precious.pyc").read_text() == "keep"
    assert (repo / "src" / "module.py").read_text() == "value = 1\n"
    for name in (".venv", ".git", ".agents"):
        assert (repo / name / "keep.pyc").read_text() == "keep"
    assert sorted(path.name for path in repo.iterdir()) == [
        ".agents",
        ".git",
        ".venv",
        "scripts",
        "src",
    ]
    assert sorted(path.name for path in (repo / "src").iterdir()) == ["module.py"]


def test_clean_retains_build_outputs_until_distclean(tmp_path: Path) -> None:
    (tmp_path / "dist").mkdir()
    artifact = tmp_path / "dist" / "saved.whl"
    artifact.write_bytes(b"retained")
    (tmp_path / ".pytest_cache").mkdir()

    _run_cleaner(tmp_path)

    assert artifact.read_bytes() == b"retained"
    assert not (tmp_path / ".pytest_cache").exists()


@pytest.mark.parametrize("dist", [False, True])
def test_cleanup_preserves_custom_virtual_environment(tmp_path: Path, dist: bool) -> None:
    environment = tmp_path / "custom-environment"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("home = /python\n", encoding="utf-8")
    (environment / "sourceless.pyc").write_bytes(b"preserve environment bytecode")
    cache = environment / "package" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"preserve environment cache")
    ordinary_cache = tmp_path / "__pycache__"
    ordinary_cache.mkdir()
    (ordinary_cache / "module.pyc").write_bytes(b"generated")

    _run_cleaner(tmp_path, dist=dist)

    assert (environment / "sourceless.pyc").read_bytes() == b"preserve environment bytecode"
    assert (cache / "module.pyc").read_bytes() == b"preserve environment cache"
    assert not ordinary_cache.exists()


@pytest.mark.parametrize(
    "target",
    ["build", "dist", ".mypy_cache", ".ruff_cache", "local.egg-info", "src/local.egg-info"],
)
def test_distclean_refuses_virtual_environment_target_before_removing_anything(
    tmp_path: Path, target: str
) -> None:
    environment = tmp_path / target
    environment.mkdir(parents=True)
    (environment / "pyvenv.cfg").write_text("home = /python\n", encoding="utf-8")
    (environment / "sourceless.pyc").write_bytes(b"preserve")
    other_cache = tmp_path / ".pytest_cache"
    other_cache.mkdir()
    (other_cache / "keep").write_bytes(b"preserve until valid cleanup")

    with pytest.raises(subprocess.CalledProcessError) as raised:
        _run_cleaner(tmp_path, dist=True)

    assert b"virtual environment" in raised.value.stderr
    assert str(environment).encode() in raised.value.stderr
    assert (environment / "sourceless.pyc").read_bytes() == b"preserve"
    assert (other_cache / "keep").read_bytes() == b"preserve until valid cleanup"


@pytest.mark.parametrize("protected", [".venv", ".git", ".agents", ".codex", ".aws", "custom-env"])
def test_distclean_refuses_artifact_tree_with_protected_descendant(
    tmp_path: Path, protected: str
) -> None:
    environment = tmp_path / "build" / "nested" / protected
    environment.mkdir(parents=True)
    if protected == "custom-env":
        (environment / "pyvenv.cfg").write_text("home = /python\n", encoding="utf-8")
    precious = environment / "keep.pyc"
    precious.write_bytes(b"protected descendant")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "keep.pyc").write_bytes(b"no partial cleanup")

    with pytest.raises(subprocess.CalledProcessError) as raised:
        _run_cleaner(tmp_path, dist=True)

    assert str(environment).encode() in raised.value.stderr
    assert precious.read_bytes() == b"protected descendant"
    assert (cache / "keep.pyc").read_bytes() == b"no partial cleanup"


def test_distclean_keeps_nested_build_and_egg_info_outside_explicit_roots(tmp_path: Path) -> None:
    nested_build = tmp_path / "nested" / "build"
    nested_build.mkdir(parents=True)
    (nested_build / "saved.whl").write_bytes(b"keep nested build")
    nested_egg = tmp_path / "src" / "nested" / "local.egg-info"
    nested_egg.mkdir(parents=True)
    (nested_egg / "PKG-INFO").write_bytes(b"keep nested metadata")
    similarly_named = tmp_path / "build-not-generated"
    similarly_named.mkdir()
    (similarly_named / "source.py").write_bytes(b"keep source")

    _run_cleaner(tmp_path, dist=True)

    assert (nested_build / "saved.whl").read_bytes() == b"keep nested build"
    assert (nested_egg / "PKG-INFO").read_bytes() == b"keep nested metadata"
    assert (similarly_named / "source.py").read_bytes() == b"keep source"
