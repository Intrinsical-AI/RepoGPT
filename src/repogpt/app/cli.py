"""One explicit CLI for read analysis, publication, comparison and MCP."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import structlog

from repogpt.application.extensions import UnsupportedExtensionsError
from repogpt.application.retrieval import validate_top_k
from repogpt.domain.errors import (
    ArtifactConsistencyError,
    ArtifactPublicationError,
    CollectionFailure,
    InvalidRepoError,
    InvalidRequestError,
    InvalidRetrievalArtifactError,
    OutputStreamClosed,
    OutputWriteError,
    UnsafeReplacementError,
)
from repogpt.domain.operations import OperationResult
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_repository_operations
from repogpt.stdio import silence_failed_stdout


def _non_negative_int(value: str) -> int:
    number = int(value)
    validate_top_k(number)
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze, export and query repository structure.", allow_abbrev=False
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("analyze", "export"):
        action = commands.add_parser(command, allow_abbrev=False)
        action.add_argument("repo_path")
        action.add_argument("--projection", choices=["ast", "code-units"], default="ast")
        action.add_argument("--include-tests", action="store_true")
        action.add_argument("--extensions")
        action.add_argument("--flatten", choices=["node", "file"], default=argparse.SUPPRESS)
        action.add_argument("--fail-fast", action="store_true")
        action.add_argument("--repo-key")
        action.add_argument("--log-level", choices=["INFO", "DEBUG"], default="INFO")
        if command == "analyze":
            action.add_argument("--response-mode", choices=["summary", "inline"], default="summary")
        else:
            target = action.add_mutually_exclusive_group(required=True)
            target.add_argument("--output")
            target.add_argument("--stdout", action="store_true")
            action.add_argument("--format", choices=["json", "ndjson"], default="json")
            action.add_argument("--replace-scope", action="store_true")
    compare = commands.add_parser("compare", allow_abbrev=False)
    compare.add_argument("artifact_path")
    compare.add_argument("query")
    compare.add_argument("--top-k", type=_non_negative_int, default=3)
    commands.add_parser("mcp", allow_abbrev=False)
    return parser


def _status(outcome: OperationResult) -> int:
    if outcome.stopped_early:
        return 1
    if outcome.payload.get("stats", {}).get("failed_files", 0):
        return 2
    return 0


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.command == "mcp":
        from repogpt.app.mcp_cli import main as serve_mcp

        return serve_mcp()
    if args.command in {"analyze", "export"}:
        if not args.repo_path.strip():
            parser.error("repo_path must not be blank")
        if args.projection == "code-units" and hasattr(args, "flatten"):
            parser.error("--flatten only applies to --projection ast")
    configure_logging(getattr(args, "log_level", "INFO"))
    log = structlog.get_logger()
    operations = build_repository_operations()
    try:
        if args.command == "compare":
            outcome = operations.compare(args.artifact_path, args.query, args.top_k)
        else:
            options: dict[str, Any] = {
                "repo_path": args.repo_path,
                "projection": args.projection,
                "include_tests": args.include_tests,
                "extensions": None if args.extensions is None else args.extensions.split(","),
                "flatten": getattr(args, "flatten", "node"),
                "fail_fast": args.fail_fast,
                "repo_key": args.repo_key,
            }
            if args.command == "analyze":
                outcome = operations.analyze(**options, response_mode=args.response_mode)
            else:
                outcome = operations.export(
                    **options,
                    output_path=None if args.stdout else args.output,
                    format=args.format,
                    replace_scope=args.replace_scope,
                )
        if args.command != "export" or not args.stdout:
            try:
                print(json.dumps(outcome.payload, ensure_ascii=False, allow_nan=False), flush=True)
            except BrokenPipeError as exc:
                raise OutputStreamClosed from exc
            except OSError as exc:
                raise OutputWriteError(str(exc)) from exc
        for failure in outcome.payload.get("failures", []):
            log.error(
                "aborting — fail-fast" if outcome.stopped_early else "parse error",
                path=failure["path"],
                error=failure.get("error", "parse failed"),
            )
        return _status(outcome)
    except (UnsupportedExtensionsError, InvalidRequestError) as exc:
        parser.error(exc.message if isinstance(exc, UnsupportedExtensionsError) else str(exc))
    except InvalidRepoError as exc:
        log.error("invalid repository path", error=str(exc))
        return 3
    except ArtifactConsistencyError as exc:
        log.error("analysis consistency error", error=str(exc))
        return 3
    except (CollectionFailure, UnsafeReplacementError, InvalidRetrievalArtifactError) as exc:
        log.error("operation failed", error=str(exc))
        return 3
    except OutputStreamClosed:
        silence_failed_stdout()
        return 0
    except OutputWriteError as exc:
        log.error("stdout I/O error", error=str(exc))
        silence_failed_stdout()
        return 3
    except ArtifactPublicationError as exc:
        log.error("output I/O error", destination=exc.destination, error=str(exc))
        return 3
    except OSError as exc:
        log.error("operation I/O error", error=str(exc))
        return 3
    except Exception as exc:
        log.error("unexpected operation error", exception_type=type(exc).__name__)
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
