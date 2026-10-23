from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog

from repogpt.adapters.writers.artifact_writer import ArtifactWriter, file_output_path
from repogpt.application.exit_codes import (
    EXIT_OPERATIONAL_ERROR,
    EXIT_SUCCESS,
    exit_code_for_result,
)
from repogpt.application.extensions import UnsupportedExtensionsError
from repogpt.domain.errors import (
    ArtifactConsistencyError,
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
    parser.add_argument("--extensions")
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

    to_stdout = bool(args.stdout or (args.output and Path(args.output).as_posix() == "/dev/stdout"))
    default_output = "code_units.json" if args.emit == "code-units" else "analysis.json"
    output_path = None if to_stdout else Path(args.output or default_output)

    try:
        request = analyzer.request(
            repo_path=args.repo_path,
            projection=args.emit,
            include_tests=args.include_tests,
            extensions=None if args.extensions is None else args.extensions.split(","),
            format=args.format,
            flatten=flatten or "node",
            fail_fast=args.fail_fast,
            repo_key=args.repo_key,
            replace_scope=args.replace_scope,
        )
        if output_path is not None:
            try:
                output_path = file_output_path(
                    str(output_path),
                    repo_root=request.repo_root,
                    supported_extensions=analyzer.parser_registry.supported_extensions(),
                )
            except OSError as exc:
                log.error("output I/O error", error=str(exc))
                return EXIT_OPERATIONAL_ERROR
        result, projection = analyzer.run(request)
    except UnsupportedExtensionsError as exc:
        parser.error(exc.message)
    except InvalidRequestError as exc:
        parser.error(str(exc))
    except InvalidRepoError as exc:
        log.error("invalid repository path", error=str(exc))
        return EXIT_OPERATIONAL_ERROR
    except ArtifactConsistencyError as exc:
        log.error("analysis consistency error", error=str(exc))
        return EXIT_OPERATIONAL_ERROR
    except (CollectionFailure, UnsafeReplacementError, OSError) as exc:
        log.error("analysis aborted", error=str(exc))
        return EXIT_OPERATIONAL_ERROR
    except Exception as exc:
        log.error("unexpected error", error=str(exc))
        return EXIT_OPERATIONAL_ERROR

    try:
        ArtifactWriter().write(projection, output_path, format=request.format)
    except InvalidRequestError as exc:
        parser.error(str(exc))
    except OSError as exc:
        if output_path is None:
            silence_failed_stdout()
            if isinstance(exc, BrokenPipeError):
                return EXIT_SUCCESS
        log.error("output I/O error", error=str(exc))
        return EXIT_OPERATIONAL_ERROR
    except Exception as exc:
        log.error("unexpected error", error=str(exc))
        return EXIT_OPERATIONAL_ERROR

    for parsed_file in result.parsed_files:
        if parsed_file.failure is not None:
            log.error(
                "aborting — fail-fast" if result.stopped_early else "parse error",
                path=parsed_file.relative_path,
                error=parsed_file.failure.message,
            )
    return exit_code_for_result(result)


if __name__ == "__main__":
    sys.exit(main())
