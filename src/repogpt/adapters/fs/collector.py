from __future__ import annotations

from pathlib import Path

import pathspec
import structlog

from repogpt.domain.analysis import AnalysisRequest
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

logger = structlog.get_logger(__name__)


def load_pathspec(repo_root: Path) -> pathspec.PathSpec | None:
    ignore_file = repo_root / ".repogptignore"
    try:
        if ignore_file.exists():
            with ignore_file.open("r", encoding="utf-8") as handle:
                lines = [
                    line for line in handle if line.strip() and not line.strip().startswith("#")
                ]
            return pathspec.PathSpec.from_lines("gitignore", lines)
    except OSError:
        logger.warning("failed to read repogptignore", path=str(ignore_file))
    return None


def ignore_reason(p: Path, repo_root: Path, spec: pathspec.PathSpec | None = None) -> str | None:
    rel = p.relative_to(repo_root)
    if any(part in DEFAULT_IGNORES for part in rel.parts):
        return "default_ignore"
    try:
        if p.is_symlink():
            return "symlink"
    except OSError:
        return "symlink_error"
    if spec and spec.match_file(str(rel)):
        return "repogptignore"
    return None


def should_ignore(p: Path, repo_root: Path, spec: pathspec.PathSpec | None = None) -> bool:
    return ignore_reason(p, repo_root, spec) is not None


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
        paths = sorted(
            repo_root.rglob("*"),
            key=lambda path: path.relative_to(repo_root).as_posix(),
        )
        for path in paths:
            relative_path = path.relative_to(repo_root).as_posix()
            reason = ignore_reason(path, repo_root, spec)
            if reason is not None:
                self._record_skip_if_file(skipped, path, relative_path, reason)
                continue
            try:
                if not path.is_file():
                    continue
            except OSError:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="is_file_error",
                    )
                )
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
            try:
                file_size = path.stat().st_size
            except OSError:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="stat_failed",
                    )
                )
                continue
            if file_size > request.max_file_size:
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason="file_too_large",
                    )
                )
                continue
            if is_likely_binary(path):
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

    def _is_test_path(self, path: Path, repo_root: Path) -> bool:
        rel_parts = path.relative_to(repo_root).parts
        return "tests" in rel_parts or path.name.startswith(("test_", "test-"))

    def _record_skip_if_file(
        self,
        skipped: list[SkippedFile],
        path: Path,
        relative_path: str,
        reason: str,
    ) -> None:
        try:
            if path.is_file():
                skipped.append(
                    SkippedFile(
                        abs_path=path,
                        relative_path=relative_path,
                        reason=reason,
                    )
                )
        except OSError:
            skipped.append(
                SkippedFile(
                    abs_path=path,
                    relative_path=relative_path,
                    reason=f"{reason}_is_file_error",
                )
            )
