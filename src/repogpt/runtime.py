from __future__ import annotations

from repogpt.adapters.fs.collector import DefaultCollector
from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.adapters.parsers.registry import StaticParserRegistry
from repogpt.adapters.projectors.ast_projector import AstProjector
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector
from repogpt.application.analyze_repo import AnalyzeRepo


def build_analyze_repo() -> AnalyzeRepo:
    return AnalyzeRepo(
        collector=DefaultCollector(),
        loader=DefaultLoader(),
        parser_registry=StaticParserRegistry(),
        ast_projector=AstProjector(),
        code_units_projector=CodeUnitsProjector(),
    )
