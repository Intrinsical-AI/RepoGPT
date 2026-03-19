from __future__ import annotations

import traceback

from repogpt.domain.analysis import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisStats,
    AstProjection,
    CodeUnitsProjection,
)
from repogpt.domain.errors import InvalidRepoError, ParseFailure
from repogpt.domain.files import ParsedFile
from repogpt.ports.collector import CollectorPort
from repogpt.ports.loader import LoaderPort
from repogpt.ports.parsers import ParserRegistryPort
from repogpt.ports.projectors import AstProjectorPort, CodeUnitsProjectorPort
from repogpt.ports.writers import ArtifactWriterPort


class AnalyzeRepo:
    def __init__(
        self,
        *,
        collector: CollectorPort,
        loader: LoaderPort,
        parser_registry: ParserRegistryPort,
        ast_projector: AstProjectorPort,
        code_units_projector: CodeUnitsProjectorPort,
        writer: ArtifactWriterPort,
    ) -> None:
        self.collector = collector
        self.loader = loader
        self.parser_registry = parser_registry
        self.ast_projector = ast_projector
        self.code_units_projector = code_units_projector
        self.writer = writer

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        repo_root = request.repo_root.resolve()
        if not repo_root.exists():
            raise InvalidRepoError(f"Repository path '{repo_root}' does not exist")
        if not repo_root.is_dir():
            raise InvalidRepoError(f"Repository path '{repo_root}' is not a directory")

        supported_extensions = self.parser_registry.supported_extensions()
        if request.supported_languages is not None:
            enabled_extensions = set(request.supported_languages)
        else:
            enabled_extensions = set(supported_extensions)

        collected_files, skipped_files = self.collector.collect(request, enabled_extensions)
        parsed_files: list[ParsedFile] = []
        stopped_early = False

        for collected_file in collected_files:
            loaded_file = self.loader.load(collected_file)
            parser = self.parser_registry.parser_for(loaded_file.language)
            if parser is None:
                parsed_file = ParsedFile(
                    loaded_file=loaded_file,
                    root=None,
                    failure=ParseFailure("no parser"),
                )
            else:
                try:
                    root = parser.parse(loaded_file)
                    parsed_file = ParsedFile(loaded_file=loaded_file, root=root)
                except Exception as exc:  # noqa: BLE001
                    parsed_file = ParsedFile(
                        loaded_file=loaded_file,
                        root=None,
                        failure=ParseFailure(self._format_failure(exc)),
                    )
            parsed_files.append(parsed_file)
            if parsed_file.failure is not None and request.fail_fast:
                stopped_early = True
                break

        stats = AnalysisStats(
            total_files=len(parsed_files),
            ok_files=sum(1 for parsed_file in parsed_files if parsed_file.root is not None),
            failed_files=sum(1 for parsed_file in parsed_files if parsed_file.failure is not None),
            skipped_files=len(skipped_files),
        )
        result = AnalysisResult(
            parsed_files=parsed_files,
            skipped_files=skipped_files,
            stats=stats,
            stopped_early=stopped_early,
        )

        projection: AstProjection | CodeUnitsProjection
        if request.projection == "code_units":
            projection = self.code_units_projector.project(result, request)
        else:
            projection = self.ast_projector.project(result, request)
        self.writer.write(projection, request)
        return result

    def _format_failure(self, exc: Exception) -> str:
        return "\n".join(traceback.format_exception_only(type(exc), exc)).strip()
