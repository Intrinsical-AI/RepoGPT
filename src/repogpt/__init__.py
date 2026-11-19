from __future__ import annotations

import logging
from importlib.metadata import version

__version__ = version("repogpt")

logging.getLogger(__name__).addHandler(logging.NullHandler())
