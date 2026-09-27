"""MCP server for RepoGPT artifact emission and profile comparison."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal, cast

from repogpt import __version__
from repogpt.adapters.parsers.registry import StaticParserRegistry
from repogpt.application.export_policy import REPO_KEY_PATTERN
from repogpt.application.languages import UnsupportedLanguagesError, normalize_language_filter
from repogpt.domain.analysis import AnalysisRequest, AstProjection
from repogpt.domain.errors import InvalidRequestError
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_analyze_repo
from repogpt.stdio import silence_failed_stdout
from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import compare_profiles

logger = logging.getLogger("repogpt_mcp")


def _run_repogpt_analysis(
    *,
    emit: Literal["ast", "code-units"],
    repo_path: str,
    include_tests: bool,
    languages: list[str] | None,
    fail_fast: bool,
    repo_key: str | None = None,
    replace_scope: bool = False,
    flatten: Literal["node", "file"] = "node",
    fmt: Literal["json", "ndjson"] = "json",
) -> dict[str, Any]:
    registry = StaticParserRegistry()
    request = AnalysisRequest(
        repo_root=Path(repo_path),
        include_tests=include_tests,
        supported_languages=normalize_language_filter(
            languages,
            supported_extensions=registry.supported_extensions(),
        ),
        projection="code_units" if emit == "code-units" else "ast",
        format=fmt,
        flatten_kind=flatten,
        fail_fast=fail_fast,
        repo_key=repo_key,
        replace_scope=replace_scope,
    )
    result, projection = build_analyze_repo().run(request)
    if fmt == "json":
        artifact: dict[str, Any] | list[dict[str, Any]] = projection.json_payload
    else:
        artifact = cast(AstProjection, projection).ndjson_records

    return {
        "content": [{"type": "text", "text": json.dumps(artifact, indent=2)}],
        "isError": result.stats.failed_files > 0,
    }


def tool_emit_code_units(
    repo_path: str,
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
    repo_key: str | None = None,
    replace_scope: bool = False,
) -> dict[str, Any]:
    return _run_repogpt_analysis(
        emit="code-units",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        repo_key=repo_key,
        replace_scope=replace_scope,
    )


def tool_emit_ast(
    repo_path: str,
    flatten: Literal["node", "file"] = "node",
    format: Literal["json", "ndjson"] = "json",
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
) -> dict[str, Any]:
    return _run_repogpt_analysis(
        emit="ast",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        flatten=flatten,
        fmt=format,
    )


def tool_compare_profiles(artifact_path: str, query: str) -> dict[str, Any]:
    documents = load_documents(Path(artifact_path))
    return {
        "content": [
            {"type": "text", "text": json.dumps(compare_profiles(documents, query_text=query))}
        ],
        "isError": False,
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
                "repo_key": {"type": "string", "pattern": "^" + REPO_KEY_PATTERN + "$"},
                "replace_scope": {"type": "boolean", "default": False},
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


def _error(req_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    """Check wire fields/types; handlers apply the shared semantic policies."""
    properties = schema["properties"]
    missing = set(schema.get("required", [])) - arguments.keys()
    unknown = arguments.keys() - properties.keys()
    if missing or unknown:
        raise InvalidRequestError(
            f"invalid argument fields: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    for name, value in arguments.items():
        definition = properties[name]
        kind = definition["type"]
        valid_type = (
            (kind == "boolean" and type(value) is bool)
            or (kind == "string" and isinstance(value, str))
            or (
                kind == "array"
                and isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            )
        )
        if not valid_type:
            raise InvalidRequestError(f"{name} must be {kind}")
        if "enum" in definition and value not in definition["enum"]:
            raise InvalidRequestError(f"{name} must be one of {definition['enum']}")
        if name in {"repo_path", "artifact_path"} and not value.strip():
            raise InvalidRequestError(f"{name} must not be blank")


def handle_request(request: object) -> dict[str, Any] | None:
    if not isinstance(request, dict):
        return _error(None, -32600, "request must be an object")
    req_id = request.get("id")
    valid_id = type(req_id) in {str, int}
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _error(req_id if valid_id else None, -32600, "invalid JSON-RPC envelope")
    if "id" not in request:
        # Notifications never produce responses or invoke request-only tools.
        return None
    if not valid_id:
        return _error(None, -32600, "id must be a string or integer")
    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _error(req_id, -32602, "params must be an object")
    result: dict[str, Any]
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "repogpt", "version": __version__},
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": spec["input_schema"],
                }
                for name, spec in TOOLS.items()
            ]
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or tool_name not in TOOLS:
            return _error(req_id, -32602, f"Unknown tool: {tool_name}")
        tool_args = params.get("arguments", {})
        if not isinstance(tool_args, dict):
            return _error(req_id, -32602, "tool arguments must be an object")
        try:
            _validate_arguments(tool_args, TOOLS[tool_name]["input_schema"])
            result = TOOLS[tool_name]["handler"](**tool_args)
        except (InvalidRequestError, UnsupportedLanguagesError) as exc:
            return _error(req_id, -32602, str(exc))
        except Exception as exc:
            # A tool failure must not kill the stdio session.
            logger.error("Tool error in %s: %s", tool_name, exc)
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return _error(req_id, -32601, f"Unknown method: {method}")
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main() -> int:
    configure_logging()
    logger.info("RepoGPT MCP Server starting...")
    response: dict[str, Any] | None
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except ValueError as exc:
                response = _error(None, -32700, f"Parse error: {exc}")
            else:
                response = handle_request(request)
            if response is not None:
                print(json.dumps(response), flush=True)
    except BrokenPipeError:
        silence_failed_stdout()
        return 0
    except OSError as exc:
        silence_failed_stdout()
        logger.error("stdio I/O error: %s", exc)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
