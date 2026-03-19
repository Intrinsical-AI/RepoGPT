from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Any

from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, AstProjection
from repogpt.domain.files import ParsedFile
from repogpt.ports.projectors import AstProjectorPort
from repogpt.utils.tree_utils import flatten_tree

SCHEMA_VERSION = "1"


class AstProjector(AstProjectorPort):
    def project(self, result: AnalysisResult, request: AnalysisRequest) -> AstProjection:
        node_records = [
            node
            for parsed_file in result.parsed_files
            for node in self._yield_node_records(parsed_file, request)
        ]
        failure_records = [
            self._failure_record(parsed_file)
            for parsed_file in result.parsed_files
            if parsed_file.failure is not None
        ]
        summary = self._summary_record(
            request=request,
            result=result,
            emitted_records=len(node_records),
        )
        return AstProjection(
            schema_version=SCHEMA_VERSION,
            json_payload={
                "schema_version": SCHEMA_VERSION,
                "repo_root": request.repo_root.resolve().as_posix(),
                "stats": summary["stats"],
                "failures": failure_records,
                "records": node_records,
            },
            ndjson_records=[*node_records, *failure_records, summary],
        )

    def _yield_node_records(
        self,
        parsed_file: ParsedFile,
        request: AnalysisRequest,
    ) -> Iterable[dict[str, Any]]:
        if parsed_file.root is None:
            return []
        nodes = (
            flatten_tree(parsed_file.root)
            if request.flatten_kind == "node"
            else [dataclasses.asdict(parsed_file.root)]
        )
        return [
            {
                "record_type": "node",
                "schema_version": SCHEMA_VERSION,
                **node,
                "path": str(parsed_file.relative_path or node.get("path") or ""),
                "file": {
                    "size": parsed_file.digest.size,
                    "sha256": parsed_file.digest.sha256,
                },
            }
            for node in nodes
        ]

    def _failure_record(self, parsed_file: ParsedFile) -> dict[str, Any]:
        assert parsed_file.failure is not None
        return {
            "record_type": "failure",
            "schema_version": SCHEMA_VERSION,
            "path": parsed_file.relative_path,
            "language": parsed_file.language,
            "error": parsed_file.failure.message,
            "file": {
                "size": parsed_file.digest.size,
                "sha256": parsed_file.digest.sha256,
            },
        }

    def _summary_record(
        self,
        *,
        request: AnalysisRequest,
        result: AnalysisResult,
        emitted_records: int,
    ) -> dict[str, Any]:
        return {
            "record_type": "summary",
            "schema_version": SCHEMA_VERSION,
            "repo_root": request.repo_root.resolve().as_posix(),
            "stats": {
                "total_files": result.stats.total_files,
                "ok_files": result.stats.ok_files,
                "failed_files": result.stats.failed_files,
                "emitted_records": emitted_records,
            },
        }
