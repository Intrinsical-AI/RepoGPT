from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog

from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.application.exit_codes import exit_code_for_result
from repogpt.application.languages import UnsupportedLanguagesError, parse_cli_languages
from repogpt.domain.analysis import AnalysisRequest
from repogpt.domain.errors import (
    CollectionFailure,
    InvalidRepoError,
    InvalidRequestError,
    UnsafeReplacementError,
)
from repogpt.logging_config import configure_logging
from repogpt.runtime import build_analyze_repo
from repogpt.stdio import silence_failed_stdout


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a code repository and output structured summaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("repo_path")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument(
        "--flatten",
        choices=["node", "file"],
        default=argparse.SUPPRESS,
        help="AST layout (default: node)",
    )
    parser.add_argument("--format", choices=["json", "ndjson"], default="json")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--stdout", action="store_true")
    output.add_argument("-o", "--output")
    parser.add_argument("--languages")
    parser.add_argument("--emit", choices=["ast", "code-units"], default="ast")
    parser.add_argument("--log-level", choices=["INFO", "DEBUG"], default="INFO")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--repo-key", help="Explicit code-units identity shared across clones")
    parser.add_argument(
        "--replace-scope",
        action="store_true",
        help="Request replacement from a complete code-units export",
    )

    args = parser.parse_args()
    if not args.repo_path.strip():
        parser.error("repo_path must not be blank")
    flatten = getattr(args, "flatten", None)
    if args.emit == "code-units" and flatten is not None:
        parser.error("--flatten only applies to --emit ast")

    configure_logging(args.log_level)
    log = structlog.get_logger()
    analyzer = build_analyze_repo()

    try:
        langs = parse_cli_languages(
            args.languages,
            supported_extensions=analyzer.parser_registry.supported_extensions(),
        )
    except UnsupportedLanguagesError as exc:
        parser.error(exc.message)
    to_stdout = bool(args.stdout or (args.output and Path(args.output).as_posix() == "/dev/stdout"))
    default_output = "code_units.json" if args.emit == "code-units" else "analysis.json"
    output_path = None if to_stdout else Path(args.output or default_output)

    request = AnalysisRequest(
        repo_root=Path(args.repo_path),
        include_tests=args.include_tests,
        supported_languages=langs,
        projection="code_units" if args.emit == "code-units" else "ast",
        format=args.format,
        flatten_kind=flatten or "node",
        fail_fast=args.fail_fast,
        repo_key=args.repo_key,
        replace_scope=args.replace_scope,
    )

    try:
        result, projection = analyzer.run(request)
        ArtifactWriter().write(projection, output_path, format=request.format)
        for parsed_file in result.parsed_files:
            if parsed_file.failure is not None:
                log.error(
                    "aborting — fail-fast" if result.stopped_early else "parse error",
                    path=parsed_file.relative_path,
                    error=parsed_file.failure.message,
                )
        return exit_code_for_result(result)
    except InvalidRequestError as exc:
        parser.error(str(exc))
    except InvalidRepoError as exc:
        log.error("invalid repository path", error=str(exc))
        return 3
    except (CollectionFailure, UnsafeReplacementError) as exc:
        log.error("analysis aborted", error=str(exc))
        return 3
    except OSError as exc:
        if output_path is None:
            silence_failed_stdout()
            if isinstance(exc, BrokenPipeError):
                return 0
        log.error("output I/O error", error=str(exc))
        return 3
    except Exception as exc:
        log.error("unexpected error", error=str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
