from __future__ import annotations

from typing import Protocol

from repogpt.domain.analysis import (
    AnalysisRequest,
    AnalysisResult,
    AstProjection,
    CodeUnitsProjection,
)


class AstProjectorPort(Protocol):
    def project(self, result: AnalysisResult, request: AnalysisRequest) -> AstProjection: ...


class CodeUnitsProjectorPort(Protocol):
    def project(self, result: AnalysisResult, request: AnalysisRequest) -> CodeUnitsProjection: ...
