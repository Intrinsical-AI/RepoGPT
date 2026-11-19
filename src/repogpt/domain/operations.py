"""Transport-neutral operation results and publication evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactWriteReceipt:
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class OperationResult:
    payload: dict[str, Any]
    is_error: bool = False
    stopped_early: bool = False
