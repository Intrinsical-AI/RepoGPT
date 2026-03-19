from __future__ import annotations

from typing import Protocol

from repogpt.domain.analysis import AnalysisRequest
from repogpt.domain.files import CollectedFile, SkippedFile


class CollectorPort(Protocol):
    def collect(
        self,
        request: AnalysisRequest,
        supported_extensions: set[str],
    ) -> tuple[list[CollectedFile], list[SkippedFile]]: ...
