"""MCP server for RepoGPT artifact emission and profile comparison."""

from __future__ import annotations

import json
import stat
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, cast

import structlog

from repogpt import __version__
from repogpt.adapters.projectors.ast_projector import SCHEMA_VERSION as AST_SCHEMA_VERSION
from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.application.export_policy import REPO_KEY_PATTERN
from repogpt.application.extensions import UnsupportedExtensionsError, normalize_extension_filter
from repogpt.domain.analysis import AnalysisRequest, AstProjection
from repogpt.domain.code_units import SCHEMA_VERSION as CODE_UNITS_SCHEMA_VERSION
from repogpt.domain.errors import InvalidRequestError
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_analyze_repo
from repogpt.stdio import silence_failed_stdout
from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import (
    FLAT_PROFILE,
    STRUCTURED_PROFILE,
    compare_profiles,
    validate_top_k,
)

logger = structlog.get_logger(__name__)


def _result(payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def _file_output_path(value: str) -> Path:
    if not value.strip() or value in {"-", "/dev/stdin", "/dev/stdout", "/dev/stderr"}:
        raise InvalidRequestError("output_path must name an artifact file, not standard I/O")
    candidate = Path(value)
    # Resolve directories without following a leaf symlink into its target.
    output_path = candidate.parent.resolve(strict=True) / candidate.name
    try:
        mode = output_path.lstat().st_mode
    except FileNotFoundError:
        return output_path
    if not stat.S_ISREG(mode):
        raise InvalidRequestError("output_path must be a regular file or a new file")
    return output_path


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
    output_path: str | None = None,
) -> dict[str, Any]:
    destination = _file_output_path(output_path) if output_path is not None else None
    analyzer = build_analyze_repo()
    supported_extensions = analyzer.parser_registry.supported_extensions()
    request = AnalysisRequest(
        repo_root=Path(repo_path),
        include_tests=include_tests,
        supported_extensions=normalize_extension_filter(
            languages,
            supported_extensions=supported_extensions,
        ),
        projection="code_units" if emit == "code-units" else "ast",
        format=fmt,
        flatten_kind=flatten,
        fail_fast=fail_fast,
        repo_key=repo_key,
        replace_scope=replace_scope,
    )
    if (
        destination is not None
        and destination.suffix.lstrip(".").lower() in supported_extensions
        and destination.is_relative_to(request.repo_root.resolve())
        and destination.exists()
    ):
        # Selection filters and fail-fast can leave source files out of parsed_files.
        raise InvalidRequestError("output_path must not overwrite a repository source file")
    result, projection = analyzer.run(request)
    artifact: dict[str, Any]
    if destination is not None:
        receipt = ArtifactWriter().write(projection, destination, format=fmt)
        artifact = {
            "output_path": str(destination),
            "format": fmt,
            "schema_version": projection.json_payload["schema_version"],
            "size_bytes": receipt.size_bytes,
            "sha256": receipt.sha256,
            "stats": projection.json_payload["stats"],
        }
    elif fmt == "json":
        artifact = projection.json_payload
    else:
        artifact = {
            "schema_version": projection.json_payload["schema_version"],
            "format": "ndjson",
            "records": cast(AstProjection, projection).ndjson_records,
        }

    return _result(artifact, is_error=result.stats.failed_files > 0)


def tool_emit_code_units(
    repo_path: str,
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
    repo_key: str | None = None,
    replace_scope: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    return _run_repogpt_analysis(
        emit="code-units",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        repo_key=repo_key,
        replace_scope=replace_scope,
        output_path=output_path,
    )


def tool_emit_ast(
    repo_path: str,
    flatten: Literal["node", "file"] = "node",
    format: Literal["json", "ndjson"] = "json",
    include_tests: bool = False,
    languages: list[str] | None = None,
    fail_fast: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    return _run_repogpt_analysis(
        emit="ast",
        repo_path=repo_path,
        include_tests=include_tests,
        languages=languages,
        fail_fast=fail_fast,
        flatten=flatten,
        fmt=format,
        output_path=output_path,
    )


def tool_compare_profiles(artifact_path: str, query: str, top_k: int = 3) -> dict[str, Any]:
    try:
        validate_top_k(top_k)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    documents = load_documents(Path(artifact_path))
    return _result(compare_profiles(documents, query_text=query, top_k=top_k), is_error=False)


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _error_schema() -> dict[str, Any]:
    return _object_schema({"error": {"type": "string"}})


def _artifact_output_schema(emit: Literal["ast", "code-units"]) -> dict[str, Any]:
    version = AST_SCHEMA_VERSION if emit == "ast" else CODE_UNITS_SCHEMA_VERSION
    source: dict[str, Any] = json.loads(
        files("repogpt")
        .joinpath("schemas")
        .joinpath(f"{emit}-v{version}.schema.json")
        .read_text(encoding="utf-8")
    )
    branches: list[dict[str, Any]]
    if emit == "ast":
        branches = [
            {"$ref": "#/$defs/envelope"},
            _object_schema(
                {
                    "schema_version": {"const": version},
                    "format": {"const": "ndjson"},
                    "records": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"$ref": f"#/$defs/{name}"}
                                for name in ("nodeRecord", "failureRecord", "summaryRecord")
                            ]
                        },
                    },
                }
            ),
        ]
    else:
        branches = [
            {key: value for key, value in source.items() if key not in {"$defs", "$schema", "$id"}}
        ]
    branches.extend(
        [
            _object_schema(
                {
                    "output_path": {"type": "string", "minLength": 1},
                    "format": {"enum": ["json", "ndjson"] if emit == "ast" else ["json"]},
                    "schema_version": {"const": version},
                    "size_bytes": {"type": "integer", "minimum": 0},
                    "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "stats": {"$ref": "#/$defs/stats"},
                }
            ),
            _error_schema(),
        ]
    )
    return {"type": "object", "$defs": source["$defs"], "oneOf": branches}


def _comparison_output_schema() -> dict[str, Any]:
    profile = _object_schema(
        {
            "seed_count": {"type": "integer", "minimum": 0},
            "expanded_count": {"type": "integer", "minimum": 0},
            "estimated_tokens": {"type": "integer", "minimum": 0},
            "context_characters": {"type": "integer", "minimum": 0},
            "context_segment_count": {"type": "integer", "minimum": 0},
            "external_ids": {"type": "array", "items": {"type": "string"}},
        }
    )
    return {
        "type": "object",
        "oneOf": [
            _object_schema(
                {
                    "query_text": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 0},
                    FLAT_PROFILE: profile,
                    STRUCTURED_PROFILE: profile,
                }
            ),
            _error_schema(),
        ],
    }


TOOLS: dict[str, dict[str, Any]] = {
    "repogpt_emit_code_units": {
        "description": "Emit RepoGPT code-units v6 inline or atomically replace an output file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "include_tests": {"type": "boolean"},
                "languages": {"type": "array", "items": {"type": "string"}},
                "fail_fast": {"type": "boolean"},
                "repo_key": {"type": "string", "pattern": "^" + REPO_KEY_PATTERN + "$"},
                "replace_scope": {"type": "boolean", "default": False},
                "output_path": {"type": "string"},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        "output_schema": _artifact_output_schema("code-units"),
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "handler": tool_emit_code_units,
    },
    "repogpt_emit_ast": {
        "description": "Emit AST v3 inline or atomically replace a JSON/NDJSON output file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "flatten": {"type": "string", "enum": ["node", "file"]},
                "format": {"type": "string", "enum": ["json", "ndjson"]},
                "include_tests": {"type": "boolean"},
                "languages": {"type": "array", "items": {"type": "string"}},
                "fail_fast": {"type": "boolean"},
                "output_path": {"type": "string"},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        "output_schema": _artifact_output_schema("ast"),
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "handler": tool_emit_ast,
    },
    "repogpt_compare_profiles": {
        "description": "Compare flat and structured retrieval bundles over a code-units artifact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_path": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 0, "default": 3},
            },
            "required": ["artifact_path", "query"],
            "additionalProperties": False,
        },
        "output_schema": _comparison_output_schema(),
        "annotations": {"readOnlyHint": True},
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
            or (kind == "integer" and type(value) is int)
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
        if "minimum" in definition and value < definition["minimum"]:
            raise InvalidRequestError(f"{name} must be >= {definition['minimum']}")
        if name in {"repo_path", "artifact_path", "output_path"} and not value.strip():
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
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "repogpt", "version": __version__},
            "capabilities": {"tools": {}},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": spec["input_schema"],
                    "outputSchema": spec["output_schema"],
                    "annotations": spec["annotations"],
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
        except (InvalidRequestError, UnsupportedExtensionsError) as exc:
            return _error(req_id, -32602, str(exc))
        except Exception as exc:
            # A tool failure must not kill the stdio session.
            logger.error("tool error", tool=tool_name, error=str(exc))
            result = _result({"error": str(exc)}, is_error=True)
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
                print(json.dumps(response, ensure_ascii=False, separators=(",", ":")), flush=True)
    except BrokenPipeError:
        silence_failed_stdout()
        return 0
    except OSError as exc:
        silence_failed_stdout()
        logger.error("stdio I/O error", error=str(exc))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
