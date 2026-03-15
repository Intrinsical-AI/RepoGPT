from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import structlog

from repogpt.adapters.publisher.code_units_publisher import CodeUnitsPublisher
from repogpt.adapters.collector.simple_collector import SimpleCollector
from repogpt.adapters.parser import parsers
from repogpt.adapters.pipeline.simple_pipeline import SimplePipeline
from repogpt.adapters.publisher.simple_publisher import SimplePublisher
from repogpt.core.service import CodeRepoAnalysisService
from repogpt.models import AnalysisConf

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

    langs = _parse_languages_arg(args.languages)
    if langs is not None:
        unsupported = sorted(set(langs) - set(parsers.keys()))
        if unsupported:
            parser.error(
                "unsupported languages: "
                + ", ".join(unsupported)
                + "; supported: "
                + ", ".join(sorted(parsers.keys()))
            )
    if args.emit == "code-units" and args.format != "json":
        parser.error("--emit code-units only supports --format json")
    to_stdout = args.stdout or (args.output and Path(args.output).as_posix() == "/dev/stdout")

    conf = AnalysisConf(
        repo_path=Path(args.repo_path).resolve(),
        include_tests=args.include_tests,
        output=None if to_stdout else Path(args.output) if args.output else None,
        flatten_kind=args.flatten,
        output_format=args.format,
        to_stdout=to_stdout,
        emit_kind=args.emit,
        languages=langs,
        log_level=args.log_level,
        fail_fast=args.fail_fast,
    )

    log.info("starting run", repo=str(conf.repo_path), format=conf.output_format)

    try:
        return CodeRepoAnalysisService(
            collector=SimpleCollector(),
            pipeline=SimplePipeline(parsers=parsers, processors={}),
            publisher=(
                CodeUnitsPublisher() if conf.emit_kind == "code-units" else SimplePublisher()
            ),
        ).run(runtime_conf=conf)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        log.error("invalid repository path", error=str(exc))
        return 3
    except Exception as exc:
        log.error("unexpected error", error=str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
