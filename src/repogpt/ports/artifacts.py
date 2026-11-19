"""Admission and publication contract for generated artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol, overload

from repogpt.domain.analysis import AstProjection, CodeUnitsProjection
from repogpt.domain.operations import ArtifactWriteReceipt


class ArtifactPublisher(Protocol):
    def destination(
        self, value: str, *, repo_root: Path, supported_extensions: set[str]
    ) -> Path: ...

    @overload
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: Path,
        *,
        format: Literal["json", "ndjson"] = "json",
        receipt_check: Callable[[ArtifactWriteReceipt], None] | None = None,
    ) -> ArtifactWriteReceipt: ...

    @overload
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: None,
        *,
        format: Literal["json", "ndjson"] = "json",
        receipt_check: Callable[[ArtifactWriteReceipt], None] | None = None,
    ) -> None: ...
