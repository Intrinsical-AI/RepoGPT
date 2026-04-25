from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("repogpt")
except PackageNotFoundError:  # pragma: no cover - source tree without package metadata
    __version__ = "0.0.0+local"

logging.getLogger(__name__).addHandler(logging.NullHandler())
