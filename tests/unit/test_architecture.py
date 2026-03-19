from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_application_layer_does_not_import_io_or_logging_details() -> None:
    imports = _imports_for(REPO_ROOT / "src/repogpt/application/analyze_repo.py")
    assert "json" not in imports
    assert "sys" not in imports
    assert "structlog" not in imports
    assert "pathspec" not in imports


def test_fs_adapters_do_not_import_parsers() -> None:
    imports = _imports_for(REPO_ROOT / "src/repogpt/adapters/fs/collector.py")
    assert all(not name.startswith("repogpt.adapters.parsers") for name in imports)


def test_registry_is_only_source_of_supported_extensions() -> None:
    imports = _imports_for(REPO_ROOT / "src/repogpt/app/cli.py")
    assert "repogpt.adapters.parsers.registry" in imports
    assert "repogpt.adapters.parsers.py_parser" not in imports
    assert "repogpt.adapters.parsers.md_parser" not in imports
