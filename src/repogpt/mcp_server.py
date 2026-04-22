"""MCP server for RepoGPT artifact emission and profile comparison."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal, cast

from repogpt import __version__
from repogpt.domain.analysis import (
    AnalysisRequest,
    AstProjection,
    CodeUnitsProjection,
    OutputTarget,
)
from repogpt.application.exit_codes import exit_code_for_result
from repogpt.runtime import build_analyze_repo
from repogpt.utils.retrieval_profiles import compare_profiles

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("repogpt_mcp")


class _CaptureWriter:
    def __init__(self) -> None:
        self.projection: AstProjection | CodeUnitsProjection | None = None

    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        request: AnalysisRequest,
    ) -> None:
        _ = request
        self.projection = projection


def _build_request(
    *,
    repo_path: str,
    emit: Literal["ast", "code-units"],
    include_tests: bool,
    languages: list[str] | None,
    fail_fast: bool,
    flatten: Literal["node", "file"] | None = None,
    fmt: Literal["json", "ndjson"] = "json",
) -> AnalysisRequest:
    return AnalysisRequest(
        repo_root=Path(repo_path).resolve(),
        include_tests=include_tests,
        supported_languages=languages,
        projection="code_units" if emit == "code-units" else "ast",
        format=fmt,
        flatten_kind=flatten or "node",
        output_target=OutputTarget(),
        fail_fast=fail_fast,
    )


def _run_repogpt_analysis(
    *,
    emit: Literal["ast", "code-units"],
    repo_path: str,
    include_tests: bool,
    languages: list[str] | None,
    fail_fast: bool,
    flatten: Literal["node", "file"] | None = None,
    fmt: Literal["json", "ndjson"] = "json",
) -> dict[str, Any]:
    request = _build_request(
        repo_path=repo_path,
        emit=emit,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        flatten=flatten,
        fmt=fmt,
    )
    capture_writer = _CaptureWriter()
    result = build_analyze_repo(capture_writer).run(request)
    if capture_writer.projection is None:
        raise RuntimeError("RepoGPT analysis did not produce a projection.")
    if fmt == "json":
        artifact: dict[str, Any] | list[dict[str, Any]] = capture_writer.projection.json_payload
    else:
        projection = cast(AstProjection, capture_writer.projection)
        artifact = projection.ndjson_records

    return {
        "exit_code": exit_code_for_result(result),
        "artifact": artifact,
        "stderr": "",
    }


def tool_emit_code_units(
    repo_path: str,
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
) -> dict[str, Any]:
    return _run_repogpt_analysis(
        emit="code-units",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
    )


def tool_emit_ast(
    repo_path: str,
    flatten: str = "node",
    format: str = "json",
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
) -> dict[str, Any]:
    if flatten not in {"node", "file"}:
        raise ValueError("flatten must be one of node or file.")
    if format not in {"json", "ndjson"}:
        raise ValueError("format must be one of json or ndjson.")
    return _run_repogpt_analysis(
        emit="ast",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        flatten=cast(Literal["node", "file"], flatten),
        fmt=cast(Literal["json", "ndjson"], format),
    )


def tool_compare_profiles(artifact_path: str, query: str) -> dict[str, Any]:
    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("expected a code-units payload with a documents array")
    return {
        "exit_code": 0,
        "comparison": compare_profiles(
            [document for document in documents if isinstance(document, dict)],
            query_text=query,
        ),
        "stderr": "",
    }


TOOLS: dict[str, dict[str, Any]] = {
    "repogpt_emit_code_units": {
        "description": "Emit RepoGPT code-units v4 as a JSON artifact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "include_tests": {"type": "boolean"},
                "languages": {"type": "array", "items": {"type": "string"}},
                "fail_fast": {"type": "boolean"},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        "handler": tool_emit_code_units,
    },
    "repogpt_emit_ast": {
        "description": "Emit RepoGPT AST artifacts as JSON or NDJSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "flatten": {"type": "string", "enum": ["node", "file"]},
                "format": {"type": "string", "enum": ["json", "ndjson"]},
                "include_tests": {"type": "boolean"},
                "languages": {"type": "array", "items": {"type": "string"}},
                "fail_fast": {"type": "boolean"},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        "handler": tool_emit_ast,
    },
    "repogpt_compare_profiles": {
        "description": "Compare flat and structured retrieval bundles over a code-units artifact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["artifact_path", "query"],
            "additionalProperties": False,
        },
        "handler": tool_compare_profiles,
    },
}


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "repogpt", "version": __version__},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": name,
                        "description": spec["description"],
                        "inputSchema": spec["input_schema"],
                    }
                    for name, spec in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        if not isinstance(params, dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "params must be an object"},
            }
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        if not isinstance(tool_args, dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "tool arguments must be an object"},
            }
        try:
            result = TOOLS[str(tool_name)]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception as exc:
            logger.error("Tool error in %s: %s", tool_name, exc)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> None:
    logger.info("RepoGPT MCP Server starting...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            print(json.dumps(response), flush=True)
        except Exception as exc:  # pragma: no cover - defensive stdio guard
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            print(json.dumps(error_response), flush=True)


if __name__ == "__main__":
    main()
