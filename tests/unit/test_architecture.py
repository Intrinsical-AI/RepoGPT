from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package = ".".join(path.relative_to(SRC_ROOT).parent.parts)
                module = resolve_name("." * node.level + module, package)
            imports.add(module)
            imports.update(f"{module}.{alias.name}" for alias in node.names)
    return imports


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "repogpt" or len(parts) < 2 or parts[1].startswith("_"):
        return None
    if parts[1] in {"app", "mcp_server", "runtime", "logging_config", "stdio"}:
        return "interfaces"
    return parts[1]


def test_internal_imports_respect_layer_dependencies() -> None:
    allowed = {
        "domain": set(),
        "ports": {"domain"},
        "utils": {"domain"},
        "application": {"domain", "ports", "utils"},
        "adapters": {"domain", "ports", "utils"},
        "interfaces": {"domain", "ports", "utils", "application", "adapters"},
    }
    violations = []
    for path in sorted((SRC_ROOT / "repogpt").rglob("*.py")):
        source = _layer(".".join(path.relative_to(SRC_ROOT).with_suffix("").parts))
        if source is None:
            continue
        assert source in allowed, f"Unclassified layer: {path}"
        for module in sorted(_imports_for(path)):
            target = _layer(module)
            if target is not None and target != source and target not in allowed[source]:
                violations.append(f"{path.relative_to(SRC_ROOT)} -> {module}")
    assert not violations, "\n".join(violations)


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
    runtime_imports = _imports_for(REPO_ROOT / "src/repogpt/runtime.py")
    cli_imports = _imports_for(REPO_ROOT / "src/repogpt/app/cli.py")
    assert "repogpt.adapters.parsers.registry" in runtime_imports
    assert "repogpt.runtime" in cli_imports
    assert "repogpt.adapters.parsers.registry" not in cli_imports
    assert "repogpt.adapters.parsers.py_parser" not in cli_imports
    assert "repogpt.adapters.parsers.md_parser" not in cli_imports
