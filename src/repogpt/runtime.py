from __future__ import annotations

from repogpt.adapters.fs.collector import DefaultCollector
from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.adapters.parsers.registry import StaticParserRegistry
from repogpt.adapters.projectors.ast_projector import AstProjector
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector
from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.application.analyze_repo import AnalyzeRepo
from repogpt.application.operations import RepositoryOperations


def build_analyze_repo() -> AnalyzeRepo:
    return AnalyzeRepo(
        collector=DefaultCollector(),
        loader=DefaultLoader(),
        parser_registry=StaticParserRegistry(),
        ast_projector=AstProjector(),
        code_units_projector=CodeUnitsProjector(),
    )


def build_repository_operations() -> RepositoryOperations:
    return RepositoryOperations(build_analyze_repo(), ArtifactWriter())
