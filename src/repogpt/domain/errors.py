from __future__ import annotations

from dataclasses import dataclass


class InvalidRepoError(Exception):
    """Raised when the repository path is invalid or unusable."""


class CollectionFailure(Exception):
    """Raised when collection cannot proceed safely."""


class InvalidRequestError(ValueError):
    """Raised before analysis when requested options are inconsistent."""


class UnsafeReplacementError(Exception):
    """Raised when analysis cannot satisfy an explicit scope replacement request."""


@dataclass(frozen=True)
class ParseFailure:
    message: str
