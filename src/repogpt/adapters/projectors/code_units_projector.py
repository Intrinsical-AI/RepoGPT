from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from repogpt.adapters.projectors._common import failure_record, file_digest
from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, CodeUnitsProjection
from repogpt.domain.code_units import KIND, SCHEMA_VERSION
from repogpt.domain.files import ParsedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.projectors import CodeUnitsProjectorPort
from repogpt.utils.text_processing import physical_lines
from repogpt.utils.tree_utils import iter_nodes

CONTAINER_TYPES = {"module", "class", "heading"}


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "repo"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _residual_module_content(
    lines: list[str], selected: list[CodeNode]
) -> tuple[str, list[dict[str, int]]]:
    """Keep physical lines outside every emitted non-module unit."""
    covered = [False] * len(lines)
    for node in selected:
        if node.type == "module":
            continue
        start, end = node.start_line, node.end_line
        if start is None or end is None or not 1 <= start <= end <= len(lines):
            raise ValueError(f"Invalid source span for {node.type} in {node.path}")
        for index in range(start - 1, end):
            covered[index] = True

    ranges: list[dict[str, int]] = []
    content: list[str] = []
    uncovered_start: int | None = None
    for index, is_covered in enumerate([*covered, True], start=1):
        if not is_covered and uncovered_start is None:
            uncovered_start = index
        elif is_covered and uncovered_start is not None:
            end = index - 1
            ranges.append({"start_line": uncovered_start, "end_line": end})
            content.extend(lines[uncovered_start - 1 : end])
            uncovered_start = None
    return "".join(content), ranges


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
            failure_record(parsed_file, schema_version=SCHEMA_VERSION)
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
        source_id = f"repogpt:{repo_key}:file:{parsed_file.relative_path}"
        lines = physical_lines(parsed_file.text, keepends=True)
        residual_content, residual_ranges = _residual_module_content(lines, selected)
        nodes = {node.id: node for node in iter_nodes(parsed_file.root)}
        selected_ids = {node.id for node in selected}
        ancestors_by_id = {node.id: self._ancestors(node=node, nodes=nodes) for node in selected}
        container_ids = {
            ancestor.id
            for ancestors in ancestors_by_id.values()
            for ancestor in ancestors
            if ancestor.id in selected_ids
        }
        external_ids, qualified_names = self._identities(
            root=parsed_file.root,
            repo_key=repo_key,
            relative_path=parsed_file.relative_path,
        )
        docs: list[dict[str, Any]] = []
        for node in selected:
            if node.type == "module":
                span_content = residual_content
            else:
                assert node.start_line is not None and node.end_line is not None
                span_content = "".join(lines[node.start_line - 1 : node.end_line])
            content_hash = _content_hash(span_content)
            unit_level = self._unit_level(node=node, container_ids=container_ids)
            qualified_name = qualified_names[node.id]
            ancestors = ancestors_by_id[node.id]
            container = self._container_node(
                node=node, ancestors=ancestors, selected_ids=selected_ids
            )
            container_id = external_ids[container.id]
            depth = len(ancestors)
            ancestor_path = [qualified_names[ancestor.id] for ancestor in ancestors]
            docstring_present = bool(node.docstring and node.docstring.strip())
            has_children = bool(node.children)
            doc: dict[str, Any] = {
                "external_id": external_ids[node.id],
                "source_id": source_id,
                "repo_key": repo_key,
                "scope": scope,
                "snapshot_id": snapshot_id,
                "path": parsed_file.relative_path,
                "language": node.language,
                "unit_type": node.type,
                "unit_level": unit_level,
                "symbol": None if node.type == "code_block" else node.name,
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
                    "file": file_digest(parsed_file.digest, sha_first=True),
                    "tags": list(node.tags or []),
                    "attributes": dict(node.attributes or {}),
                    "dependencies": list(node.dependencies or []),
                },
            }
            if node.type == "module":
                doc["content_ranges"] = residual_ranges
            docs.append(doc)
        return docs

    def _select_nodes(self, root: CodeNode) -> list[CodeNode]:
        nodes = iter_nodes(root)
        if root.language == "py":
            return [root, *(node for node in nodes if node.type in {"function", "method", "class"})]
        if root.language == "md":
            return [root, *(node for node in nodes if node.type in {"code_block", "heading"})]
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

    def _unit_level(self, *, node: CodeNode, container_ids: set[str]) -> str:
        return "container" if node.type in CONTAINER_TYPES or node.id in container_ids else "symbol"

    def _container_node(
        self, *, node: CodeNode, ancestors: list[CodeNode], selected_ids: set[str]
    ) -> CodeNode:
        if node.type == "module":
            return node
        for ancestor in reversed(ancestors):
            if ancestor.id in selected_ids:
                return ancestor
        raise ValueError(f"No emitted container for {node.type} in {node.path}")

    def _ancestors(self, *, node: CodeNode, nodes: dict[str, CodeNode]) -> list[CodeNode]:
        ancestors: list[CodeNode] = []
        current = node
        while current.parent_id is not None:
            parent = nodes[current.parent_id]
            ancestors.append(parent)
            current = parent
        ancestors.reverse()
        return ancestors
