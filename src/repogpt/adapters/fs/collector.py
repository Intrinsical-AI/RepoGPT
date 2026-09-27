from __future__ import annotations

import os
import stat
from pathlib import Path

import pathspec

from repogpt.domain.analysis import AnalysisRequest
from repogpt.domain.errors import CollectionFailure
from repogpt.domain.files import CollectedFile, SkippedFile
from repogpt.ports.collector import CollectorPort
from repogpt.utils.file_utils import is_likely_binary

DEFAULT_IGNORES: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "node_modules",
    ".tox",
    ".DS_Store",
    ".idea",
    ".vscode",
}


def load_pathspec(repo_root: Path) -> pathspec.PathSpec | None:
    ignore_file = repo_root / ".repogptignore"
    try:
        ignore_file.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CollectionFailure(f"Cannot inspect {ignore_file}: {exc}") from exc
    try:
        with ignore_file.open("r", encoding="utf-8") as handle:
            return pathspec.GitIgnoreSpec.from_lines(handle)
    except (OSError, ValueError, UnicodeError) as exc:
        raise CollectionFailure(f"Cannot read .repogptignore: {exc}") from exc


def ignore_reason(p: Path, repo_root: Path, spec: pathspec.PathSpec | None = None) -> str | None:
    rel = p.relative_to(repo_root)
    if any(part in DEFAULT_IGNORES for part in rel.parts):
        return "default_ignore"
    try:
        mode = p.lstat().st_mode
    except OSError as exc:
        raise CollectionFailure(f"Cannot inspect {rel}: {exc}") from exc
    if stat.S_ISLNK(mode):
        return "symlink"
    if spec and _matches_pathspec(spec, rel, is_dir=stat.S_ISDIR(mode)):
        return "repogptignore"
    return None


class DefaultCollector(CollectorPort):
    def collect(
        self,
        request: AnalysisRequest,
        supported_extensions: set[str],
    ) -> tuple[list[CollectedFile], list[SkippedFile]]:
        repo_root = request.repo_root.resolve()
        spec = load_pathspec(repo_root)
        files: list[CollectedFile] = []
        skipped: list[SkippedFile] = []
        paths = self._candidate_files(repo_root=repo_root, spec=spec)
        for path in paths:
            relative_path = path.relative_to(repo_root).as_posix()
            reason = ignore_reason(path, repo_root, spec)
            if reason is not None:
                skipped.append(SkippedFile(path, relative_path, reason))
                continue
            try:
                info = path.stat()
            except OSError as exc:
                raise CollectionFailure(f"Cannot stat {relative_path}: {exc}") from exc
            if not stat.S_ISREG(info.st_mode):
                continue
            extension = path.suffix.lstrip(".").lower()
            if extension not in supported_extensions:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="unsupported_extension",
                    )
                )
                continue
            if not request.include_tests and self._is_test_path(path, repo_root):
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="tests_excluded",
                    )
                )
                continue
            file_size = info.st_size
            if file_size > request.max_file_size:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="file_too_large",
                    )
                )
                continue
            try:
                binary = is_likely_binary(path)
            except OSError as exc:
                raise CollectionFailure(f"Cannot read {relative_path}: {exc}") from exc
            if binary:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="binary_file",
                    )
                )
                continue
            files.append(
                CollectedFile(
                    abs_path=path,
                    relative_path=relative_path,
                    language=extension,
                )
            )
        return files, skipped

    def _candidate_files(
        self,
        *,
        repo_root: Path,
        spec: pathspec.PathSpec | None,
    ) -> list[Path]:
        candidates: list[Path] = []

        def onerror(error: OSError) -> None:
            raise CollectionFailure(
                f"Cannot traverse {error.filename or repo_root}: {error}"
            ) from error

        for dirpath, dirnames, filenames in os.walk(repo_root, topdown=True, onerror=onerror):
            current_dir = Path(dirpath)
            kept_dirs: list[str] = []
            for dirname in sorted(dirnames):
                path = current_dir / dirname
                if ignore_reason(path, repo_root, spec) is None:
                    kept_dirs.append(dirname)
            dirnames[:] = kept_dirs

            for filename in sorted(filenames):
                candidates.append(current_dir / filename)

        return sorted(
            candidates,
            key=lambda path: path.relative_to(repo_root).as_posix(),
        )

    def _is_test_path(self, path: Path, repo_root: Path) -> bool:
        rel_parts = path.relative_to(repo_root).parts
        return "tests" in rel_parts or path.name.startswith(("test_", "test-"))


def _matches_pathspec(spec: pathspec.PathSpec, rel: Path, *, is_dir: bool) -> bool:
    relative_path = rel.as_posix() + ("/" if is_dir else "")
    return spec.match_file(relative_path)
