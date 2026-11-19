"""Repository operations shared by CLI and MCP, independent of either transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from repogpt.application.analyze_repo import AnalyzeRepo
from repogpt.application.retrieval import compare_profiles
from repogpt.domain.analysis import AnalysisResult, AstProjection, CodeUnitsProjection
from repogpt.domain.errors import (
    ArtifactConsistencyError,
    ArtifactPublicationError,
    InvalidRetrievalArtifactError,
    OutputStreamClosed,
    OutputWriteError,
)
from repogpt.domain.operations import ArtifactWriteReceipt, OperationResult
from repogpt.ports.artifacts import ArtifactPublisher
from repogpt.utils.retrieval_artifact import load_documents

MAX_FAILURE_SUMMARY_BYTES = 64 * 1024


def analysis_summary(
    result: AnalysisResult, artifact: AstProjection | CodeUnitsProjection
) -> dict[str, Any]:
    payload = artifact.json_payload
    failures: list[dict[str, Any]] = []
    failure_bytes = 0
    for failure in payload["failures"]:
        size = len(json.dumps(failure, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if failure_bytes + size > MAX_FAILURE_SUMMARY_BYTES:
            break
        failures.append(failure)
        failure_bytes += size
    complete = not (
        result.stopped_early
        or result.stats.failed_files
        or any(item.reason in {"file_too_large", "binary_file"} for item in result.skipped_files)
    )
    return {
        "projection": "ast" if isinstance(artifact, AstProjection) else "code-units",
        "schema_version": payload["schema_version"],
        "complete": complete,
        "stats": payload["stats"],
        "failures": failures,
        "failure_count": len(payload["failures"]),
        "failures_truncated": len(failures) != len(payload["failures"]),
    }


class RepositoryOperations:
    """Own operation semantics; transports own serialization and response budgets.

    A file result policy is evaluated before publication. Rejection therefore
    preserves the previous destination, including when an MCP receipt is too large.
    """

    def __init__(self, analyzer: AnalyzeRepo, publisher: ArtifactPublisher) -> None:
        self.analyzer = analyzer
        self.publisher = publisher

    def analyze(
        self,
        repo_path: str,
        projection: Literal["ast", "code-units"] = "ast",
        response_mode: Literal["summary", "inline"] = "summary",
        include_tests: bool = False,
        extensions: list[str] | None = None,
        fail_fast: bool = False,
        repo_key: str | None = None,
        flatten: Literal["node", "file"] = "node",
    ) -> OperationResult:
        request = self.analyzer.request(
            repo_path=repo_path,
            projection=projection,
            include_tests=include_tests,
            extensions=extensions,
            fail_fast=fail_fast,
            repo_key=repo_key,
            flatten=flatten,
        )
        result, artifact = self.analyzer.run(request)
        payload = analysis_summary(result, artifact)
        if response_mode == "inline":
            payload["artifact"] = artifact.json_payload
        return OperationResult(
            payload, is_error=not payload["complete"], stopped_early=result.stopped_early
        )

    def export(
        self,
        repo_path: str,
        output_path: str | None,
        projection: Literal["ast", "code-units"] = "ast",
        format: Literal["json", "ndjson"] = "json",
        include_tests: bool = False,
        extensions: list[str] | None = None,
        fail_fast: bool = False,
        repo_key: str | None = None,
        replace_scope: bool = False,
        flatten: Literal["node", "file"] = "node",
        *,
        result_policy: Callable[[OperationResult], OperationResult] | None = None,
    ) -> OperationResult:
        request = self.analyzer.request(
            repo_path=repo_path,
            projection=projection,
            include_tests=include_tests,
            extensions=extensions,
            fail_fast=fail_fast,
            repo_key=repo_key,
            replace_scope=replace_scope,
            flatten=flatten,
            format=format,
        )
        try:
            destination = (
                None
                if output_path is None
                else self.publisher.destination(
                    output_path,
                    repo_root=request.repo_root,
                    supported_extensions=self.analyzer.parser_registry.supported_extensions(),
                )
            )
        except OSError as exc:
            raise ArtifactPublicationError(str(output_path), exc) from exc
        result, artifact = self.analyzer.run(request)
        summary = analysis_summary(result, artifact)
        if destination is None:
            try:
                self.publisher.write(artifact, None, format=format)
            except BrokenPipeError as exc:
                raise OutputStreamClosed from exc
            except OSError as exc:
                raise OutputWriteError(str(exc)) from exc
            return OperationResult(
                summary, is_error=not summary["complete"], stopped_early=result.stopped_early
            )

        prepared: OperationResult | None = None

        def check(receipt: ArtifactWriteReceipt) -> None:
            nonlocal prepared
            outcome = OperationResult(
                {
                    **summary,
                    "output_path": str(destination),
                    "format": format,
                    "size_bytes": receipt.size_bytes,
                    "sha256": receipt.sha256,
                },
                is_error=not summary["complete"],
                stopped_early=result.stopped_early,
            )
            prepared = result_policy(outcome) if result_policy is not None else outcome

        try:
            self.publisher.write(artifact, destination, format=format, receipt_check=check)
        except OSError as exc:
            raise ArtifactPublicationError(str(destination), exc) from exc
        if prepared is None:
            raise ArtifactConsistencyError("Publisher omitted the publication receipt check")
        return prepared

    def compare(self, artifact_path: str, query: str, top_k: int = 3) -> OperationResult:
        try:
            return OperationResult(
                compare_profiles(load_documents(Path(artifact_path)), query_text=query, top_k=top_k)
            )
        except ValueError as exc:
            raise InvalidRetrievalArtifactError(str(exc)) from exc
