"""Native optional SDK transport over RepoGPT application and writer operations."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import anyio
from jsonschema import Draft202012Validator, ValidationError
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError

from repogpt import __version__
from repogpt.adapters.writers.artifact_writer import ArtifactWriter, file_output_path
from repogpt.application.export_policy import REPO_KEY_PATTERN
from repogpt.application.extensions import UnsupportedExtensionsError
from repogpt.domain.analysis import AnalysisResult, AstProjection, CodeUnitsProjection
from repogpt.domain.errors import (
    ArtifactConsistencyError,
    CollectionFailure,
    InvalidRepoError,
    InvalidRequestError,
    InvalidRetrievalArtifactError,
    UnsafeReplacementError,
)
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_analyze_repo
from repogpt.stdio import silence_failed_stdout
from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import FLAT_PROFILE, STRUCTURED_PROFILE, compare_profiles

MAX_RESPONSE_BYTES = 256 * 1024
MAX_FAILURE_SUMMARY_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolOutcome:
    payload: dict[str, Any]
    is_error: bool = False


def _analysis_payload(
    result: AnalysisResult, artifact: AstProjection | CodeUnitsProjection
) -> dict[str, Any]:
    payload = artifact.json_payload
    failures: list[dict[str, Any]] = []
    failure_bytes = 0
    for failure in payload["failures"]:
        encoded_size = len(json.dumps(failure, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if failure_bytes + encoded_size > MAX_FAILURE_SUMMARY_BYTES:
            break
        failures.append(failure)
        failure_bytes += encoded_size
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


def analyze(
    repo_path: str,
    projection: Literal["ast", "code-units"] = "ast",
    response_mode: Literal["summary", "inline"] = "summary",
    include_tests: bool = False,
    extensions: list[str] | None = None,
    fail_fast: bool = False,
    repo_key: str | None = None,
    flatten: Literal["node", "file"] = "node",
) -> ToolOutcome:
    analyzer = build_analyze_repo()
    request = analyzer.request(
        repo_path=repo_path,
        projection=projection,
        include_tests=include_tests,
        extensions=extensions,
        fail_fast=fail_fast,
        repo_key=repo_key,
        flatten=flatten,
    )
    result, artifact = analyzer.run(request)
    payload = _analysis_payload(result, artifact)
    if response_mode == "inline":
        payload["artifact"] = artifact.json_payload
    return ToolOutcome(payload, is_error=not payload["complete"])


def export(
    repo_path: str,
    output_path: str,
    projection: Literal["ast", "code-units"] = "ast",
    format: Literal["json", "ndjson"] = "json",
    include_tests: bool = False,
    extensions: list[str] | None = None,
    fail_fast: bool = False,
    repo_key: str | None = None,
    replace_scope: bool = False,
    flatten: Literal["node", "file"] = "node",
) -> ToolOutcome:
    analyzer = build_analyze_repo()
    request = analyzer.request(
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
    destination = file_output_path(
        output_path,
        repo_root=request.repo_root,
        supported_extensions=analyzer.parser_registry.supported_extensions(),
    )
    result, artifact = analyzer.run(request)
    receipt = ArtifactWriter().write(artifact, destination, format=format)
    payload = {
        **_analysis_payload(result, artifact),
        "output_path": str(destination),
        "format": format,
        "size_bytes": receipt.size_bytes,
        "sha256": receipt.sha256,
    }
    return ToolOutcome(payload, is_error=not payload["complete"])


def compare(artifact_path: str, query: str, top_k: int = 3) -> ToolOutcome:
    try:
        return ToolOutcome(
            compare_profiles(load_documents(Path(artifact_path)), query_text=query, top_k=top_k)
        )
    except ValueError as exc:
        raise InvalidRetrievalArtifactError(str(exc)) from exc


def _object(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


ERROR_SCHEMA = _object(
    {"error": _object({"code": {"type": "string"}, "message": {"type": "string"}})}
)


def _analysis_schema(*, write: bool) -> dict[str, Any]:
    branches: list[dict[str, Any]] = []
    definitions: dict[str, Any] = {}
    for projection, version in (("ast", "3"), ("code-units", "6")):
        source = json.loads(
            files("repogpt")
            .joinpath("schemas")
            .joinpath(f"{projection}-v{version}.schema.json")
            .read_text(encoding="utf-8")
        )
        prefix = "ast_" if projection == "ast" else "code_"
        source = json.loads(json.dumps(source).replace("#/$defs/", f"#/$defs/{prefix}"))
        definitions.update({prefix + name: spec for name, spec in source["$defs"].items()})
        properties: dict[str, Any] = {
            "projection": {"const": projection},
            "schema_version": {"const": version},
            "complete": {"type": "boolean"},
            "stats": {"$ref": f"#/$defs/{prefix}stats"},
            "failures": {"type": "array", "items": {"$ref": f"#/$defs/{prefix}failureRecord"}},
            "failure_count": {"type": "integer", "minimum": 0},
            "failures_truncated": {"type": "boolean"},
        }
        if write:
            properties.update(
                {
                    "output_path": {"type": "string", "minLength": 1},
                    "format": {"enum": ["json", "ndjson"] if projection == "ast" else ["json"]},
                    "size_bytes": {"type": "integer", "minimum": 0},
                    "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                }
            )
            branches.append(_object(properties))
        else:
            branches.append(_object(properties))
            properties = dict(properties)
            properties["artifact"] = (
                {"$ref": "#/$defs/ast_envelope"}
                if projection == "ast"
                else {
                    key: value
                    for key, value in source.items()
                    if key not in {"$defs", "$id", "$schema"}
                }
            )
            branches.append(_object(properties))
    return {"type": "object", "$defs": definitions, "oneOf": [*branches, ERROR_SCHEMA]}


def _comparison_schema() -> dict[str, Any]:
    count = {"type": "integer", "minimum": 0}
    profile = _object(
        {
            **dict.fromkeys(
                (
                    "seed_count",
                    "expanded_count",
                    "estimated_tokens",
                    "context_characters",
                    "context_segment_count",
                ),
                count,
            ),
            "external_ids": {"type": "array", "items": {"type": "string"}},
        }
    )
    return {
        "type": "object",
        "oneOf": [
            _object(
                {
                    "query_text": {"type": "string"},
                    "top_k": count,
                    FLAT_PROFILE: profile,
                    STRUCTURED_PROFILE: profile,
                }
            ),
            ERROR_SCHEMA,
        ],
    }


@dataclass(frozen=True)
class ToolSpec:
    tool: types.Tool
    handler: Callable[..., ToolOutcome]
    input_validator: Draft202012Validator
    output_validator: Draft202012Validator


def _spec(
    name: str,
    description: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    handler: Callable[..., ToolOutcome],
    *,
    write: bool = False,
) -> ToolSpec:
    Draft202012Validator.check_schema(inputs)
    Draft202012Validator.check_schema(outputs)
    return ToolSpec(
        types.Tool(
            name=name,
            description=description,
            inputSchema=inputs,
            outputSchema=outputs,
            annotations=types.ToolAnnotations(
                readOnlyHint=not write, destructiveHint=write, openWorldHint=False
            ),
        ),
        handler,
        Draft202012Validator(inputs),
        Draft202012Validator(outputs),
    )


_PATH = {"type": "string", "minLength": 1, "pattern": "\\S"}
_ANALYSIS_INPUTS: dict[str, Any] = {
    "repo_path": _PATH,
    "projection": {"enum": ["ast", "code-units"], "default": "ast"},
    "include_tests": {"type": "boolean", "default": False},
    "extensions": {"type": "array", "items": {"type": "string"}},
    "fail_fast": {"type": "boolean", "default": False},
    "repo_key": {"type": "string", "pattern": "^" + REPO_KEY_PATTERN + "$"},
    "flatten": {"enum": ["node", "file"], "default": "node"},
}
TOOLS = {
    "repogpt_analyze": _spec(
        "repogpt_analyze",
        "Analyze a repository without writes; return a summary or bounded native artifact.",
        _object(
            {
                **_ANALYSIS_INPUTS,
                "response_mode": {"enum": ["summary", "inline"], "default": "summary"},
            },
            required=["repo_path"],
        ),
        _analysis_schema(write=False),
        analyze,
    ),
    "repogpt_compare_profiles": _spec(
        "repogpt_compare_profiles",
        "Compare native flat and structured retrieval profiles over a code-units artifact.",
        _object(
            {
                "artifact_path": _PATH,
                "query": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 0, "default": 3},
            },
            required=["artifact_path", "query"],
        ),
        _comparison_schema(),
        compare,
    ),
    "repogpt_export": _spec(
        "repogpt_export",
        "Analyze and atomically publish a native artifact at an explicit destination.",
        _object(
            {
                **_ANALYSIS_INPUTS,
                "output_path": _PATH,
                "format": {"enum": ["json", "ndjson"], "default": "json"},
                "replace_scope": {"type": "boolean", "default": False},
            },
            required=["repo_path", "output_path"],
        ),
        _analysis_schema(write=True),
        export,
        write=True,
    ),
}


def _wire_result(outcome: ToolOutcome) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(
                    outcome.payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ),
            )
        ],
        structuredContent=outcome.payload,
        isError=outcome.is_error,
    )


def create_server() -> Server[Any, Any]:
    """Create an SDK server with one cancellation-safe blocking worker slot."""
    server: Server[Any, Any] = Server("repogpt", version=__version__)
    limiter = anyio.CapacityLimiter(1)

    async def list_tools(_: types.ListToolsRequest) -> types.ServerResult:
        return types.ServerResult(
            types.ListToolsResult(tools=[spec.tool for spec in TOOLS.values()])
        )

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        spec = TOOLS.get(request.params.name)
        if spec is None:
            raise McpError(types.ErrorData(code=-32602, message="Unknown tool"))
        try:
            spec.input_validator.validate(request.params.arguments or {})
        except ValidationError as exc:
            raise McpError(types.ErrorData(code=-32602, message="Invalid tool arguments")) from exc
        try:
            outcome = await anyio.to_thread.run_sync(
                partial(spec.handler, **(request.params.arguments or {})),
                limiter=limiter,
                abandon_on_cancel=False,
            )
        except (InvalidRequestError, UnsupportedExtensionsError) as exc:
            raise McpError(types.ErrorData(code=-32602, message=str(exc))) from exc
        except (
            InvalidRepoError,
            CollectionFailure,
            UnsafeReplacementError,
            ArtifactConsistencyError,
            OSError,
            InvalidRetrievalArtifactError,
        ) as exc:
            outcome = ToolOutcome(
                {"error": {"code": "operation_failed", "message": str(exc)}}, is_error=True
            )
        except Exception as exc:
            # The transport trust boundary must never expose arbitrary exception data.
            logger.error("tool_internal_error exception_type=%s", type(exc).__name__)
            raise McpError(types.ErrorData(code=-32603, message="Internal tool error")) from exc
        try:
            spec.output_validator.validate(outcome.payload)
            result = _wire_result(outcome)
            if (
                len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
                > MAX_RESPONSE_BYTES
            ):
                outcome = ToolOutcome(
                    {
                        "error": {
                            "code": "response_too_large",
                            "message": "Response exceeds 256 KiB; use repogpt_export.",
                        }
                    },
                    is_error=True,
                )
                spec.output_validator.validate(outcome.payload)
                result = _wire_result(outcome)
        except Exception as exc:
            logger.error("tool_output_error exception_type=%s", type(exc).__name__)
            raise McpError(types.ErrorData(code=-32603, message="Internal tool error")) from exc
        return types.ServerResult(result)

    # SDK @call_tool catches arbitrary exceptions and skips output validation
    # for explicit CallToolResult values. Register guarded handlers directly.
    server.request_handlers[types.ListToolsRequest] = list_tools
    server.request_handlers[types.CallToolRequest] = call_tool
    return server


class SDKDiagnosticFilter(logging.Filter):
    """Remove payloads and tracebacks from SDK diagnostics, including root calls."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name == "mcp"
            or record.name.startswith("mcp.")
            or "/mcp/" in record.pathname.replace("\\", "/")
        ):
            record.msg = "MCP diagnostic (%s)"
            record.args = (record.levelname,)
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


async def serve() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    configure_logging()
    for handler in logging.getLogger().handlers:
        handler.addFilter(SDKDiagnosticFilter())
    try:
        anyio.run(serve)
    except BaseException as exc:
        # AnyIO task groups aggregate transport failures. Inspect leaves without
        # exposing exception text or tracebacks containing request contents.
        pending = [exc]
        leaves: list[BaseException] = []
        while pending:
            item = pending.pop()
            children = getattr(item, "exceptions", None)
            if children is not None:
                pending.extend(children)
            else:
                leaves.append(item)
        if leaves and all(isinstance(item, BrokenPipeError) for item in leaves):
            silence_failed_stdout()
            return 0
        if leaves and all(isinstance(item, OSError) for item in leaves):
            silence_failed_stdout()
            logger.error("stdio I/O error")
            return 3
        if isinstance(exc, KeyboardInterrupt):
            return 0
        logger.error("server_internal_error exception_type=%s", type(exc).__name__)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
