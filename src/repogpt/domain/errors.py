from __future__ import annotations

from dataclasses import dataclass


class InvalidRepoError(Exception):
    """Raised when the repository path is invalid or unusable."""


class CollectionFailure(Exception):
    """Raised when collection cannot proceed safely."""


@dataclass(frozen=True)
class ParseFailure:
    message: str
