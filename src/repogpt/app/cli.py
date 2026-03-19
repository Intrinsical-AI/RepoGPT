from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import structlog

from repogpt.adapters.fs.collector import DefaultCollector
from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.adapters.parsers.registry import StaticParserRegistry
from repogpt.adapters.projectors.ast_projector import AstProjector
from repogpt.adapters.projectors.code_units_projector import CodeUnitsProjector
from repogpt.adapters.writers.artifact_writer import ArtifactWriter
from repogpt.application.analyze_repo import AnalyzeRepo
from repogpt.application.exit_codes import exit_code_for_result
from repogpt.domain.analysis import AnalysisRequest, OutputTarget
from repogpt.domain.errors import InvalidRepoError

LEVELS: dict[str, int] = {"DEBUG": logging.DEBUG, "INFO": logging.INFO}


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=LEVELS[level], format="%(message)s", stream=sys.stderr)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(LEVELS[level]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


def _parse_languages_arg(raw_languages: str | None) -> list[str] | None:
    if raw_languages is None:
        return None
    if raw_languages == "":
        return []
    return [lang for lang in (s.strip().lower() for s in raw_languages.split(",")) if lang]


def main() -> int:  # noqa: D401
    parser = argparse.ArgumentParser(
        description="Analyze a code repository and output structured summaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("repo_path")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--flatten", choices=["node", "file"], default="node")
    parser.add_argument("--format", choices=["json", "ndjson"], default="json")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("-o", "--output")
    parser.add_argument("--languages")
    parser.add_argument("--emit", choices=["ast", "code-units"], default="ast")
    # phase‑3 flags
    parser.add_argument("--log-level", choices=["INFO", "DEBUG"], default="INFO")
    parser.add_argument("--fail-fast", action="store_true")

    args = parser.parse_args()

    _configure_logging(args.log_level)
    log = structlog.get_logger()
    registry = StaticParserRegistry()

    langs = _parse_languages_arg(args.languages)
    if langs is not None:
        unsupported = sorted(set(langs) - registry.supported_extensions())
        if unsupported:
            parser.error(
                "unsupported languages: "
                + ", ".join(unsupported)
                + "; supported: "
                + ", ".join(sorted(registry.supported_extensions()))
            )
    if args.emit == "code-units" and args.format != "json":
        parser.error("--emit code-units only supports --format json")
    to_stdout = args.stdout or (args.output and Path(args.output).as_posix() == "/dev/stdout")

    request = AnalysisRequest(
        repo_root=Path(args.repo_path).resolve(),
        include_tests=args.include_tests,
        supported_languages=langs,
        projection="code_units" if args.emit == "code-units" else "ast",
        format=args.format,
        flatten_kind=args.flatten,
        output_target=OutputTarget(
            to_stdout=to_stdout,
            path=None if to_stdout else Path(args.output) if args.output else None,
        ),
        log_level=args.log_level,
        fail_fast=args.fail_fast,
    )

    log.info("starting run", repo=str(request.repo_root), format=request.format)

    try:
        result = AnalyzeRepo(
            collector=DefaultCollector(),
            loader=DefaultLoader(),
            parser_registry=registry,
            ast_projector=AstProjector(),
            code_units_projector=CodeUnitsProjector(),
            writer=ArtifactWriter(),
        ).run(request)
        if result.stopped_early and result.stats.failed_files > 0:
            first_failure = next(
                parsed_file.failure.message
                for parsed_file in result.parsed_files
                if parsed_file.failure is not None
            )
            log.error("aborting — fail-fast", first_error=first_failure)
        for parsed_file in result.parsed_files:
            if parsed_file.failure is not None:
                log.error(
                    "parse error", path=parsed_file.relative_path, error=parsed_file.failure.message
                )
        return exit_code_for_result(result)
    except InvalidRepoError as exc:
        log.error("invalid repository path", error=str(exc))
        return 3
    except Exception as exc:
        log.error("unexpected error", error=str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
