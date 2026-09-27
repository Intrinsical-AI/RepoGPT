from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, CodeUnitsProjection
from repogpt.domain.files import ParsedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.projectors import CodeUnitsProjectorPort
from repogpt.utils.text_processing import physical_lines
from repogpt.utils.tree_utils import iter_nodes

SCHEMA_VERSION = "4"
KIND = "code-units"
CONTAINER_TYPES = {"module", "class", "heading"}


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
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    if start_idx >= end_idx:
        return ""
    return "".join(lines[start_idx:end_idx])


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def resolve_repo_key(request: AnalysisRequest) -> str:
    if request.repo_key is not None:
        return request.repo_key
    canonical_path = os.path.normcase(str(request.repo_root.resolve()))
    return "local-" + hashlib.sha256(os.fsencode(canonical_path)).hexdigest()


def _module_external_id(*, repo_key: str, relative_path: str) -> str:
    return f"repogpt:{repo_key}:{relative_path}:module"


def _markdown_segment(value: str | None) -> str:
    return _slugify(value or "section")


class CodeUnitsProjector(CodeUnitsProjectorPort):
    def project(self, result: AnalysisResult, request: AnalysisRequest) -> CodeUnitsProjection:
        repo_key = resolve_repo_key(request)
        scope = f"repogpt:{repo_key}"
        snapshot_id = self._snapshot_id(parsed_files=result.parsed_files, repo_key=repo_key)
        ok_files = [
            parsed_file for parsed_file in result.parsed_files if parsed_file.root is not None
        ]
        failures = [
            self._failure_record(parsed_file)
            for parsed_file in result.parsed_files
            if parsed_file.failure is not None
        ]
        documents = [
            document
            for parsed_file in ok_files
            for document in self._documents_from_parsed_file(
                parsed_file=parsed_file,
                repo_key=repo_key,
                scope=scope,
                snapshot_id=snapshot_id,
            )
        ]
        external_ids = [document["external_id"] for document in documents]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("Duplicate external IDs; refusing to emit an ambiguous artifact")
        return CodeUnitsProjection(
            schema_version=SCHEMA_VERSION,
            json_payload={
                "schema_version": SCHEMA_VERSION,
                "kind": KIND,
                "repo_key": repo_key,
                "snapshot_id": snapshot_id,
                "scope": scope,
                "replace_scope": request.replace_scope,
                "stats": {
                    "total_files": result.stats.total_files,
                    "ok_files": result.stats.ok_files,
                    "failed_files": result.stats.failed_files,
                    "emitted_documents": len(documents),
                },
                "failures": failures,
                "documents": documents,
            },
        )

    def _snapshot_id(self, *, parsed_files: list[ParsedFile], repo_key: str) -> str:
        material = [
            {
                "path": parsed_file.relative_path,
                "sha256": parsed_file.digest.sha256,
            }
            for parsed_file in parsed_files
        ]
        material.sort(key=lambda item: item["path"])
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return f"{repo_key}-{digest}"

    def _documents_from_parsed_file(
        self,
        *,
        parsed_file: ParsedFile,
        repo_key: str,
        scope: str,
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        if parsed_file.root is None:
            return []
        selected = self._select_nodes(parsed_file.root)
        if not selected:
            return []
        source_id = f"repogpt:{repo_key}:file:{parsed_file.relative_path}"
        lines = physical_lines(parsed_file.text, keepends=True)
        nodes = {node.id: node for node in iter_nodes(parsed_file.root)}
        external_ids, qualified_names = self._identities(
            root=parsed_file.root,
            repo_key=repo_key,
            relative_path=parsed_file.relative_path,
        )
        docs: list[dict[str, Any]] = []
        for node in selected:
            span_content = _extract_span_text(
                content=parsed_file.text,
                lines=lines,
                start_line=node.start_line,
                end_line=node.end_line,
            )
            content_hash = _content_hash(span_content)
            unit_level = self._unit_level(node)
            qualified_name = qualified_names[node.id]
            container = self._container_node(node=node, nodes=nodes)
            container_id = external_ids[container.id]
            depth = self._depth(node=node, nodes=nodes)
            ancestor_path = self._ancestor_path(
                node=node,
                nodes=nodes,
                qualified_names=qualified_names,
            )
            docstring_present = bool(node.docstring and node.docstring.strip())
            has_children = bool(node.children)
            docs.append(
                {
                    "external_id": external_ids[node.id],
                    "source_id": source_id,
                    "repo_key": repo_key,
                    "scope": scope,
                    "snapshot_id": snapshot_id,
                    "path": parsed_file.relative_path,
                    "language": node.language,
                    "unit_type": node.type,
                    "unit_level": unit_level,
                    "symbol": node.name,
                    "qualified_name": qualified_name,
                    "container_id": container_id,
                    "depth": depth,
                    "ancestor_path": ancestor_path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "content": span_content,
                    "content_hash": content_hash,
                    "docstring_present": docstring_present,
                    "has_children": has_children,
                    "metadata": {
                        "file": {
                            "sha256": parsed_file.digest.sha256,
                            "size": parsed_file.digest.size,
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

    def _identities(
        self,
        *,
        root: CodeNode,
        repo_key: str,
        relative_path: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Assign IDs and names together so ancestry uses the same disambiguation."""
        prefix = f"repogpt:{repo_key}:{relative_path}"
        external_ids = {
            root.id: _module_external_id(repo_key=repo_key, relative_path=relative_path)
        }
        names = {root.id: relative_path}
        code_block_ordinals: dict[str, int] = {}

        def walk(parent: CodeNode, context: str) -> None:
            declaration_counts: dict[str, int] = {}
            reserved = {
                _markdown_segment(child.name)
                for child in parent.children
                if child.type == "heading"
            }
            used: set[str] = set()
            for child in parent.children:
                next_context = context
                if root.language == "py" and child.type in {"class", "function", "method"}:
                    base = child.name or ""
                    ordinal = declaration_counts.get(base, 0) + 1
                    declaration_counts[base] = ordinal
                    segment = base if ordinal == 1 else f"{base}~{ordinal}"
                    next_context = f"{context}.{segment}" if context else segment
                    names[child.id] = next_context
                    external_ids[child.id] = f"{prefix}:{child.type}:{next_context}"
                elif child.type == "heading":
                    base = _markdown_segment(child.name)
                    segment = base
                    if segment in used:
                        ordinal = 2
                        segment = f"{base}-{ordinal}"
                        while segment in used or segment in reserved:
                            ordinal += 1
                            segment = f"{base}-{ordinal}"
                    used.add(segment)
                    next_context = f"{context}/{segment}" if context else segment
                    names[child.id] = next_context
                    external_ids[child.id] = f"{prefix}:heading:{next_context}"
                elif child.type == "code_block":
                    # A heading slug can be "root" but can never contain "@".
                    section = context or "@module"
                    ordinal = code_block_ordinals.get(section, 0) + 1
                    code_block_ordinals[section] = ordinal
                    names[child.id] = f"{section}/code_block[{ordinal}]"
                    external_ids[child.id] = f"{prefix}:code_block:{section}:{ordinal}"
                walk(child, next_context)

        walk(root, "")
        return external_ids, names

    def _unit_level(self, node: CodeNode) -> str:
        return "container" if node.type in CONTAINER_TYPES else "symbol"

    def _container_node(self, *, node: CodeNode, nodes: dict[str, CodeNode]) -> CodeNode:
        if node.type == "module":
            return node
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None:
                break
            if parent.type in CONTAINER_TYPES:
                return parent
            current = parent
        return node

    def _depth(self, *, node: CodeNode, nodes: dict[str, CodeNode]) -> int:
        depth = 0
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    def _ancestor_path(
        self,
        *,
        node: CodeNode,
        nodes: dict[str, CodeNode],
        qualified_names: dict[str, str],
    ) -> list[str]:
        ancestors: list[CodeNode] = []
        current = node
        while current.parent_id is not None:
            parent = nodes.get(current.parent_id)
            if parent is None:
                break
            ancestors.append(parent)
            current = parent
        ancestors.reverse()
        return [
            qualified_names[ancestor.id] for ancestor in ancestors if ancestor.id in qualified_names
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
