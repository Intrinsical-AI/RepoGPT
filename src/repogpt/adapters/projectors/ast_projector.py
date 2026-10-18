from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from repogpt.adapters.projectors._common import failure_record, file_digest
from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, AstProjection
from repogpt.domain.files import ParsedFile
from repogpt.ports.projectors import AstProjectorPort
from repogpt.utils.tree_utils import flatten_tree, node_to_dict

SCHEMA_VERSION = "3"


class AstProjector(AstProjectorPort):
    def project(self, result: AnalysisResult, request: AnalysisRequest) -> AstProjection:
        node_records = [
            node
            for parsed_file in result.parsed_files
            for node in self._yield_node_records(parsed_file, request)
        ]
        failure_records = [
            failure_record(parsed_file, schema_version=SCHEMA_VERSION)
            for parsed_file in result.parsed_files
            if parsed_file.failure is not None
        ]
        return AstProjection(
            json_payload={
                "schema_version": SCHEMA_VERSION,
                "repo_root": request.repo_root.as_posix(),
                "stats": {
                    "total_files": result.stats.total_files,
                    "ok_files": result.stats.ok_files,
                    "failed_files": result.stats.failed_files,
                    "emitted_records": len(node_records),
                },
                "failures": failure_records,
                "records": node_records,
            },
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
            else [node_to_dict(parsed_file.root, recursive=True)]
        )
        return [
            {
                "record_type": "node",
                "schema_version": SCHEMA_VERSION,
                **node,
                "path": parsed_file.relative_path,
                "file": file_digest(parsed_file.digest),
            }
            for node in nodes
        ]
