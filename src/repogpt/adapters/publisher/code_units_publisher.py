from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import structlog

from repogpt.core.ports import PublisherPort
from repogpt.models import AnalysisConf, CodeNode, PipelineResult
from repogpt.utils.tree_utils import iter_nodes

SCHEMA_VERSION = "2"
KIND = "code-units"
logger = structlog.get_logger(__name__)


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "repo"


def _extract_span_text(
    *,
    content: str,
    lines: list[str],
    start_line: int | None,
    end_line: int | None,
) -> str:
    if start_line is None or end_line is None:
        return content
    if not lines:
        return content
    start_idx = max(0, int(start_line) - 1)
    end_idx = min(len(lines), int(end_line))
    if start_idx >= end_idx:
        return content
    return "".join(lines[start_idx:end_idx])


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _join_symbol_path(parts: list[str]) -> str:
    return ".".join(part for part in parts if part)


def _module_external_id(*, repo_key: str, relative_path: str) -> str:
    return f"repogpt:{repo_key}:{relative_path}:module"


def _markdown_segment(value: str | None) -> str:
    return _slugify(value or "section")


class CodeUnitsPublisher(PublisherPort):
    def publish(self, results: list[PipelineResult], conf: AnalysisConf) -> None:  # noqa: D401
        repo_key = _slugify(conf.repo_path.name)
        scope = f"repogpt:{repo_key}"
        snapshot_id = self._snapshot_id(results=results, repo_key=repo_key)
        ok_results = [result for result in results if result.root is not None]
        failures = [self._failure_record(result) for result in results if result.root is None]
        documents = [
            doc
            for result in ok_results
            for doc in self._documents_from_result(
                result=result,
                repo_key=repo_key,
                scope=scope,
                snapshot_id=snapshot_id,
            )
        ]

        payload = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND,
            "repo_key": repo_key,
            "snapshot_id": snapshot_id,
            "scope": scope,
            "stats": {
                "total_files": len(results),
                "ok_files": len(ok_results),
                "failed_files": len(failures),
                "emitted_documents": len(documents),
            },
            "failures": failures,
            "documents": documents,
        }

        sink_stdout = conf.to_stdout
        if sink_stdout:
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            output_path = conf.output or Path.cwd() / "code_units.json"
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info(
                "code units saved",
                path=str(output_path),
                documents=len(documents),
                fails=len(failures),
            )

        for failure in failures:
            logger.error("parse error", path=failure["path"], error=failure["error"])

    def _snapshot_id(self, *, results: list[PipelineResult], repo_key: str) -> str:
        material = [
            {
                "path": str(result.file_info.get("relative_path") or result.path.as_posix()),
                "sha256": str(result.file_info.get("sha256") or ""),
            }
            for result in results
        ]
        material.sort(key=lambda item: item["path"])
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return f"{repo_key}-{digest}"

    def _documents_from_result(
        self,
        *,
        result: PipelineResult,
        repo_key: str,
        scope: str,
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        if result.root is None:
            return []
        selected = self._select_nodes(result.root)
        if not selected:
            return []
        file_sha = str(result.file_info.get("sha256") or "")
        relative_path = str(result.file_info.get("relative_path") or result.path.as_posix())
        source_id = f"repogpt:{repo_key}:file:{relative_path}"
        content = result.content
        if content is None:
            content = result.path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        external_ids = self._external_ids_for_selected(
            root=result.root,
            selected=selected,
            repo_key=repo_key,
            relative_path=relative_path,
        )
        docs: list[dict[str, Any]] = []
        for node in selected:
            span_content = _extract_span_text(
                content=content,
                lines=lines,
                start_line=node.start_line,
                end_line=node.end_line,
            )
            docs.append(
                {
                    "external_id": external_ids[node.id],
                    "source_id": source_id,
                    "repo_key": repo_key,
                    "scope": scope,
                    "snapshot_id": snapshot_id,
                    "path": relative_path,
                    "language": node.language,
                    "unit_type": node.type,
                    "symbol": node.name,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "content": span_content,
                    "content_hash": _content_hash(span_content),
                    "metadata": {
                        "file": {
                            "sha256": file_sha,
                            "size": result.file_info.get("size"),
                        },
                        "tags": list(node.tags or []),
                        "attributes": dict(node.attributes or {}),
                        "dependencies": list(node.dependencies or []),
                    },
                }
            )
        return docs

    def _select_nodes(self, root: CodeNode) -> list[CodeNode]:
        nodes = iter_nodes(root)
        if root.language == "py":
            selected = [node for node in nodes if node.type in {"function", "method", "class"}]
            return selected or [root]
        if root.language == "md":
            selected = [node for node in nodes if node.type in {"code_block", "heading"}]
            return selected or [root]
        return [root]

    def _external_ids_for_selected(
        self,
        *,
        root: CodeNode,
        selected: list[CodeNode],
        repo_key: str,
        relative_path: str,
    ) -> dict[str, str]:
        if root.language == "py":
            return self._python_external_ids(
                root=root,
                selected=selected,
                repo_key=repo_key,
                relative_path=relative_path,
            )
        if root.language == "md":
            return self._markdown_external_ids(
                root=root,
                selected=selected,
                repo_key=repo_key,
                relative_path=relative_path,
            )
        return {
            node.id: _module_external_id(repo_key=repo_key, relative_path=relative_path)
            for node in selected
        }

    def _python_external_ids(
        self,
        *,
        root: CodeNode,
        selected: list[CodeNode],
        repo_key: str,
        relative_path: str,
    ) -> dict[str, str]:
        nodes = {node.id: node for node in iter_nodes(root)}
        selected_ids = {node.id for node in selected}
        external_ids: dict[str, str] = {}
        for node in selected:
            if node.type == "module":
                external_ids[node.id] = _module_external_id(
                    repo_key=repo_key,
                    relative_path=relative_path,
                )
                continue
            symbol_parts: list[str] = []
            current = node
            while current.parent_id is not None:
                if current.name and current.type in {"class", "function", "method"}:
                    symbol_parts.append(current.name)
                parent = nodes.get(current.parent_id)
                if parent is None:
                    break
                current = parent
                if current.id not in selected_ids and current.type == "module":
                    break
            if current.name and current.type in {"class", "function", "method"}:
                symbol_parts.append(current.name)
            qualified_symbol = _join_symbol_path(list(reversed(symbol_parts))) or (node.name or "")
            external_ids[node.id] = (
                f"repogpt:{repo_key}:{relative_path}:{node.type}:{qualified_symbol}"
            )
        return external_ids

    def _markdown_external_ids(
        self,
        *,
        root: CodeNode,
        selected: list[CodeNode],
        repo_key: str,
        relative_path: str,
    ) -> dict[str, str]:
        selected_ids = {node.id for node in selected}
        external_ids: dict[str, str] = {}
        code_block_ordinals: dict[str, int] = {}

        def walk(
            node: CodeNode,
            *,
            current_heading_path: str | None,
        ) -> None:
            heading_slug_counts: dict[str, int] = {}
            for child in node.children:
                next_heading_path = current_heading_path
                if child.type == "heading":
                    segment_base = _markdown_segment(child.name)
                    heading_slug_counts[segment_base] = heading_slug_counts.get(segment_base, 0) + 1
                    ordinal = heading_slug_counts[segment_base]
                    segment = segment_base if ordinal == 1 else f"{segment_base}-{ordinal}"
                    next_heading_path = (
                        f"{current_heading_path}/{segment}" if current_heading_path else segment
                    )
                    if child.id in selected_ids:
                        external_ids[child.id] = (
                            f"repogpt:{repo_key}:{relative_path}:heading:{next_heading_path}"
                        )
                elif child.type == "code_block":
                    section_path = current_heading_path or "root"
                    code_block_ordinals[section_path] = code_block_ordinals.get(section_path, 0) + 1
                    if child.id in selected_ids:
                        external_ids[child.id] = (
                            f"repogpt:{repo_key}:{relative_path}:code_block:"
                            f"{section_path}:{code_block_ordinals[section_path]}"
                        )
                walk(child, current_heading_path=next_heading_path)

        walk(root, current_heading_path=None)
        if root.id in selected_ids and root.id not in external_ids:
            external_ids[root.id] = _module_external_id(
                repo_key=repo_key,
                relative_path=relative_path,
            )
        return external_ids

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
