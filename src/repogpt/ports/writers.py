from __future__ import annotations

from typing import Protocol

from repogpt.domain.analysis import AnalysisRequest, AstProjection, CodeUnitsProjection


class ArtifactWriterPort(Protocol):
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        request: AnalysisRequest,
    ) -> None: ...
