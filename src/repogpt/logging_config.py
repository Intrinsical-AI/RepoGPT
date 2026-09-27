from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure entrypoint diagnostics without using the artifact/protocol stream."""
    numeric_level = {"INFO": logging.INFO, "DEBUG": logging.DEBUG}[level]
    logging.basicConfig(level=numeric_level, format="%(message)s", stream=sys.stderr, force=True)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
