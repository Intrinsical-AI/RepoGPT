"""Process-level standard-output cleanup shared by the entrypoints."""

from __future__ import annotations

import os
import sys


def silence_failed_stdout() -> None:
    """Prevent Python's shutdown flush from retrying a failed output stream."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, sys.stdout.fileno())
    finally:
        os.close(devnull)
