from __future__ import annotations

import json
import sys
from pathlib import Path

import structlog

from repogpt.domain.analysis import AnalysisRequest, AstProjection, CodeUnitsProjection
from repogpt.ports.writers import ArtifactWriterPort

logger = structlog.get_logger(__name__)


class ArtifactWriter(ArtifactWriterPort):
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        request: AnalysisRequest,
    ) -> None:
        if request.output_target.to_stdout:
            self._write_stdout(projection, request)
            return

        output_path = request.output_target.path or self._default_output_path(request)
        try:
            if isinstance(projection, AstProjection) and request.format == "ndjson":
                with output_path.open("w", encoding="utf-8") as handle:
                    for record in projection.ndjson_records:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            else:
                output_path.write_text(
                    json.dumps(projection.json_payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except OSError as exc:
            logger.error("failed to write output", path=str(output_path), error=str(exc))
            raise

    def _write_stdout(
        self,
        projection: AstProjection | CodeUnitsProjection,
        request: AnalysisRequest,
    ) -> None:
        if isinstance(projection, AstProjection) and request.format == "ndjson":
            for record in projection.ndjson_records:
                sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
            return
        json.dump(projection.json_payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

    def _default_output_path(self, request: AnalysisRequest) -> Path:
        if request.projection == "code_units":
            return Path.cwd() / "code_units.json"
        return Path.cwd() / "analysis.json"
