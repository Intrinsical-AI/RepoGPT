from __future__ import annotations

from repogpt.adapters.fs.collector import DefaultCollector
from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.adapters.parsers.registry import StaticParserRegistry
from repogpt.adapters.projectors.ast_projector import AstProjector
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector
from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.application.analyze_repo import AnalyzeRepo
from repogpt.runtime import build_analyze_repo


def test_build_analyze_repo_uses_canonical_runtime_components() -> None:
    use_case = build_analyze_repo(ArtifactWriter())

    assert isinstance(use_case, AnalyzeRepo)
    assert isinstance(use_case.collector, DefaultCollector)
    assert isinstance(use_case.loader, DefaultLoader)
    assert isinstance(use_case.parser_registry, StaticParserRegistry)
    assert isinstance(use_case.ast_projector, AstProjector)
    assert isinstance(use_case.code_units_projector, CodeUnitsProjector)
    assert isinstance(use_case.writer, ArtifactWriter)
