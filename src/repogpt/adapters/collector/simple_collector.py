from pathlib import Path

import pathspec
import structlog

from repogpt.adapters.parser import parsers
from repogpt.core.ports import CollectorPort
from repogpt.models import AnalysisConf, CollectionResult
from repogpt.utils.file_utils import is_likely_binary

# Carpeta/archivo siempre ignorados
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
    if ignore_file.exists():
        with ignore_file.open("r") as f:
            lines = [line for line in f if line.strip() and not line.strip().startswith("#")]
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    return None


def ignore_reason(p: Path, repo_root: Path, spec: pathspec.PathSpec | None = None) -> str | None:
    """Return the first ignore reason that applies to a path, if any."""
    rel = p.relative_to(repo_root)
    if any(part in DEFAULT_IGNORES for part in rel.parts):
        return "default_ignore"
    if p.is_symlink():
        return "symlink"
    if spec and spec.match_file(str(rel)):
        return "repogptignore"
    return None


def should_ignore(p: Path, repo_root: Path, spec: pathspec.PathSpec | None = None) -> bool:
    """Return True when a path should be excluded by built-ins or ignore rules."""
    return ignore_reason(p, repo_root, spec) is not None


class SimpleCollector(CollectorPort):
    def collect(self, conf: AnalysisConf) -> CollectionResult:
        repo_root = conf.repo_path.resolve()
        # sanity checks
        if not repo_root.exists():
            raise FileNotFoundError(f"Repository path '{repo_root}' does not exist")
        if not repo_root.is_dir():
            raise NotADirectoryError(f"Repository path '{repo_root}' is not a directory")

        allowed_exts = set(conf.languages) if conf.languages is not None else set(parsers.keys())
        spec = load_pathspec(repo_root)
        files: list[Path] = []
        skipped: list[Path] = []
        slogger = structlog.get_logger(__name__)
        paths = sorted(
            repo_root.rglob("*"),
            key=lambda path: path.relative_to(repo_root).as_posix(),
        )
        for p in paths:
            reason = ignore_reason(p, repo_root, spec)
            if reason is not None:
                slogger.debug("skip", path=str(p), reason=reason)
                if p.is_file():
                    skipped.append(p)
                continue
            if not p.is_file():
                continue
            if p.suffix.lstrip(".").lower() not in allowed_exts:
                slogger.debug("skip", path=str(p), reason="unsupported_extension")
                skipped.append(p)
                continue
            # Exclude tests if config requires
            if not conf.include_tests:
                rel_parts = p.relative_to(repo_root).parts
                if "tests" in rel_parts or p.name.startswith(("test_", "test-")):
                    slogger.debug("skip", path=str(p), reason="tests_excluded")
                    skipped.append(p)
                    continue

            # Filter bin files and by size
            try:
                file_size = p.stat().st_size
            except OSError:
                slogger.warning("stat failed, skipping", path=str(p))
                skipped.append(p)
                continue
            if file_size > conf.max_file_size:
                slogger.debug("skip", path=str(p), reason="file_too_large")
                skipped.append(p)
                continue
            if is_likely_binary(p):
                slogger.debug("skip", path=str(p), reason="binary_file")
                skipped.append(p)
                continue
            files.append(p)
        return CollectionResult(files=files, skipped=skipped, types=None)
