from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any

import structlog

from repogpt.core.ports import PublisherPort
from repogpt.models import AnalysisConf, PipelineResult
from repogpt.utils.tree_utils import flatten_tree

SCHEMA_VERSION = "1"
logger = structlog.get_logger(__name__)


class SimplePublisher(PublisherPort):
    def _yield_node_records(
        self, result: PipelineResult, conf: AnalysisConf
    ) -> Generator[dict[str, Any], None, None]:
        if result.root is None:
            return
        nodes = (
            flatten_tree(result.root)  # "node": lista plana, sin campo children
            if conf.flatten_kind == "node"
            else [dataclasses.asdict(result.root)]  # "file": árbol completo con children anidados
        )
        for node in nodes:
            yield {
                "record_type": "node",
                "schema_version": SCHEMA_VERSION,
                **node,
                "path": str(result.file_info.get("relative_path") or node.get("path") or ""),
                "file": {
                    "size": result.file_info.get("size"),
                    "sha256": result.file_info.get("sha256"),
                },
            }

    def _failure_record(self, result: PipelineResult) -> dict[str, Any]:
        return {
            "record_type": "failure",
            "schema_version": SCHEMA_VERSION,
            "path": str(result.file_info.get("relative_path") or result.path.as_posix()),
            "language": result.language,
            "error": result.error,
            "file": {
                "size": result.file_info.get("size"),
                "sha256": result.file_info.get("sha256"),
            },
        }

    def _summary_record(
        self,
        *,
        conf: AnalysisConf,
        total_files: int,
        ok_files: int,
        failed_files: int,
        emitted_records: int,
    ) -> dict[str, Any]:
        return {
            "record_type": "summary",
            "schema_version": SCHEMA_VERSION,
            "repo_root": conf.repo_path.resolve().as_posix(),
            "stats": {
                "total_files": total_files,
                "ok_files": ok_files,
                "failed_files": failed_files,
                "emitted_records": emitted_records,
            },
        }

    def publish(self, results: list[PipelineResult], conf: AnalysisConf) -> None:  # noqa: D401
        node_records = [
            node for result in results for node in self._yield_node_records(result, conf)
        ]
        failure_records = [
            self._failure_record(result) for result in results if result.root is None
        ]
        summary = self._summary_record(
            conf=conf,
            total_files=len(results),
            ok_files=len(results) - len(failure_records),
            failed_files=len(failure_records),
            emitted_records=len(node_records),
        )

        sink_stdout = conf.to_stdout
        if sink_stdout:
            self._write_stream(
                node_records=node_records,
                failure_records=failure_records,
                summary=summary,
                conf=conf,
            )
        else:
            output_path = conf.output or Path.cwd() / "analysis.json"
            try:
                with output_path.open("w", encoding="utf-8") as handle:
                    if conf.output_format == "json":
                        json.dump(
                            {
                                "schema_version": SCHEMA_VERSION,
                                "repo_root": conf.repo_path.resolve().as_posix(),
                                "stats": summary["stats"],
                                "failures": failure_records,
                                "records": node_records,
                            },
                            handle,
                            ensure_ascii=False,
                            indent=2,
                        )
                    else:
                        for record in self._iter_ndjson_records(
                            node_records=node_records,
                            failure_records=failure_records,
                            summary=summary,
                        ):
                            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.error("failed to write output", path=str(output_path), error=str(exc))
                raise
            logger.info(
                "analysis saved",
                path=str(output_path),
                ok=summary["stats"]["ok_files"],
                fails=summary["stats"]["failed_files"],
            )

        for failure in failure_records:
            logger.error("parse error", path=failure["path"], error=failure["error"])

    def _iter_ndjson_records(
        self,
        *,
        node_records: Iterable[dict[str, Any]],
        failure_records: Iterable[dict[str, Any]],
        summary: dict[str, Any],
    ) -> Generator[dict[str, Any], None, None]:
        yield from node_records
        yield from failure_records
        yield summary

    def _write_stream(
        self,
        *,
        node_records: list[dict[str, Any]],
        failure_records: list[dict[str, Any]],
        summary: dict[str, Any],
        conf: AnalysisConf,
    ) -> None:
        stream = sys.stdout
        if conf.output_format == "json":
            json.dump(
                {
                    "schema_version": SCHEMA_VERSION,
                    "repo_root": conf.repo_path.resolve().as_posix(),
                    "stats": summary["stats"],
                    "failures": failure_records,
                    "records": node_records,
                },
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
            return

        for record in self._iter_ndjson_records(
            node_records=node_records,
            failure_records=failure_records,
            summary=summary,
        ):
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
