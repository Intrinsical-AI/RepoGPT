"""Remove generated project artifacts without following directory symlinks."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

EXCLUDED_DIRECTORIES = {".git", ".venv", ".agents", ".codex", ".aws"}
CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache"}


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _is_virtual_environment(path: Path) -> bool:
    try:
        (path / "pyvenv.cfg").lstat()
    except FileNotFoundError:
        return False
    return True


def _walk_error(error: OSError) -> None:
    raise error


def _check_removal_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        return
    for current, directories, files in os.walk(path, followlinks=False, onerror=_walk_error):
        directory = Path(current)
        if "pyvenv.cfg" in files or "pyvenv.cfg" in directories:
            raise ValueError(f"Refusing to remove {path}: virtual environment at {directory}")
        for name in EXCLUDED_DIRECTORIES.intersection(directories + files):
            raise ValueError(f"Refusing to remove {path}: protected path {directory / name}")


def _build_artifacts(root: Path) -> list[Path]:
    targets = [
        root / name
        for name in (".mypy_cache", ".ruff_cache", "build", "dist")
        if (root / name).exists() or (root / name).is_symlink()
    ]
    for directory in (root, root / "src"):
        if (
            directory.is_dir()
            and not directory.is_symlink()
            and not _is_virtual_environment(directory)
        ):
            targets.extend(sorted(directory.glob("*.egg-info")))
    return targets


def clean_artifacts(root: Path, *, include_build: bool = False) -> None:
    """Keep source and virtual environments; unlink artifact symlinks at the leaf."""
    root = root.resolve(strict=True)
    if _is_virtual_environment(root):
        raise ValueError(f"Refusing to clean virtual environment at {root}")
    targets = _build_artifacts(root) if include_build else []
    planned = set(targets)
    for path in targets:
        _check_removal_tree(path)
    for current, directories, files in os.walk(root, followlinks=False, onerror=_walk_error):
        directory = Path(current)
        retained: list[str] = []
        for name in directories:
            path = directory / name
            if name in EXCLUDED_DIRECTORIES or path in planned:
                continue
            if path.is_symlink():
                if name in CACHE_DIRECTORIES:
                    targets.append(path)
            elif _is_virtual_environment(path):
                continue
            elif name in CACHE_DIRECTORIES:
                _check_removal_tree(path)
                targets.append(path)
            else:
                retained.append(name)
        directories[:] = retained
        for name in files:
            if name.endswith(".pyc"):
                targets.append(directory / name)
    for path in targets:
        _remove(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", action="store_true", help="Also remove build and tool caches")
    args = parser.parse_args()
    try:
        clean_artifacts(Path(__file__).resolve().parents[1], include_build=args.dist)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
