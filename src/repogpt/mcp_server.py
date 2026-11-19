"""Optional native MCP transport over transport-independent repository operations."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from importlib.resources import files
from typing import Any

import anyio
from jsonschema import Draft202012Validator, ValidationError
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError

from repogpt import __version__
from repogpt.application.export_policy import REPO_KEY_PATTERN
from repogpt.application.extensions import UnsupportedExtensionsError
from repogpt.application.retrieval import FLAT_PROFILE, STRUCTURED_PROFILE
from repogpt.domain.errors import (
    ArtifactConsistencyError,
    CollectionFailure,
    InvalidRepoError,
    InvalidRequestError,
    InvalidRetrievalArtifactError,
    UnsafeReplacementError,
)
from repogpt.domain.operations import OperationResult
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_repository_operations
from repogpt.stdio import silence_failed_stdout

MAX_RESPONSE_BYTES = 256 * 1024
logger = logging.getLogger(__name__)


class ResponseLimitError(Exception):
    """A publication receipt cannot fit before any destination is changed."""


def _analyze(**arguments: Any) -> OperationResult:
    return build_repository_operations().analyze(**arguments)


def _compare(**arguments: Any) -> OperationResult:
    return build_repository_operations().compare(**arguments)


def _bounded_export(outcome: OperationResult) -> OperationResult:
    if _fits(outcome):
        return outcome
    keys = (
        "projection",
        "schema_version",
        "complete",
        "output_path",
        "format",
        "size_bytes",
        "sha256",
    )
    compact = OperationResult(
        {**{key: outcome.payload[key] for key in keys}, "details_truncated": True},
        is_error=outcome.is_error,
    )
    if not _fits(compact):
        raise ResponseLimitError
    return compact


def _export(**arguments: Any) -> OperationResult:
    return build_repository_operations().export(**arguments, result_policy=_bounded_export)


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
            publication_properties: dict[str, Any] = {
                "output_path": {"type": "string", "minLength": 1},
                "format": {"enum": ["json", "ndjson"] if projection == "ast" else ["json"]},
                "size_bytes": {"type": "integer", "minimum": 0},
                "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            }
            properties.update(publication_properties)
            branches.append(_object(properties))
            branches.append(
                _object(
                    {
                        **{
                            key: properties[key]
                            for key in ("projection", "schema_version", "complete")
                        },
                        **publication_properties,
                        "details_truncated": {"const": True},
                    }
                )
            )
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
    handler: Callable[..., OperationResult]
    input_validator: Draft202012Validator
    output_validator: Draft202012Validator


def _spec(
    name: str,
    description: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    handler: Callable[..., OperationResult],
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
        _analyze,
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
        _compare,
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
        _export,
        write=True,
    ),
}


def _wire_result(outcome: OperationResult) -> types.CallToolResult:
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


def _fits(outcome: OperationResult) -> bool:
    return (
        len(_wire_result(outcome).model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
        <= MAX_RESPONSE_BYTES
    )


def _response_limit() -> OperationResult:
    return OperationResult(
        {
            "error": {
                "code": "response_too_large",
                "message": "Response exceeds inline limit; use a summary or file export.",
            }
        },
        is_error=True,
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
        except ResponseLimitError:
            outcome = _response_limit()
        except (
            InvalidRepoError,
            CollectionFailure,
            UnsafeReplacementError,
            ArtifactConsistencyError,
            OSError,
            InvalidRetrievalArtifactError,
        ) as exc:
            outcome = OperationResult(
                {"error": {"code": "operation_failed", "message": str(exc)}}, is_error=True
            )
        except Exception as exc:
            # The transport trust boundary must never expose arbitrary exception data.
            logger.error("tool_internal_error exception_type=%s", type(exc).__name__)
            raise McpError(types.ErrorData(code=-32603, message="Internal tool error")) from exc
        try:
            spec.output_validator.validate(outcome.payload)
            result = _wire_result(outcome)
            if not _fits(outcome):
                outcome = _response_limit()
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
    logging.getLogger("mcp").setLevel(logging.WARNING)
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
