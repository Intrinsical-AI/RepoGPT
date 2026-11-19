from __future__ import annotations

from dataclasses import dataclass


class InvalidRepoError(Exception):
    """Raised when the repository path is invalid or unusable."""


class CollectionFailure(Exception):
    """Raised when collection cannot proceed safely."""


class OutputStreamClosed(Exception):
    """The artifact consumer closed stdout during publication."""


class OutputWriteError(Exception):
    """The stdout publication failed and needs shutdown stream cleanup."""


class ArtifactPublicationError(OSError):
    """A destination admission or file publication failed before returning a receipt."""

    def __init__(self, destination: str, error: OSError) -> None:
        self.destination = destination
        super().__init__(str(error))


class FileAdmissionSkipped(Exception):
    """A selected path was safely omitted before parsing."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ArtifactConsistencyError(RuntimeError):
    """Raised when analysis cannot emit an internally consistent artifact."""


class InvalidRequestError(ValueError):
    """Raised before analysis when requested options are inconsistent."""


class UnsafeReplacementError(Exception):
    """Raised when analysis cannot satisfy an explicit scope replacement request."""


class InvalidRetrievalArtifactError(ValueError):
    """Raised when a retrieval input violates the native artifact contract."""


@dataclass(frozen=True)
class ParseFailure:
    message: str
