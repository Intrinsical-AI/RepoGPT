from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from repogpt.domain.files import ParsedFile, SkippedFile


@dataclass(frozen=True)
class OutputTarget:
    to_stdout: bool = False
    path: Path | None = None


@dataclass(frozen=True)
class AnalysisRequest:
    repo_root: Path
    include_tests: bool = False
    supported_languages: list[str] | None = None
    max_file_size: int = 2_000_000
    projection: Literal["ast", "code_units"] = "ast"
    format: Literal["json", "ndjson"] = "json"
    flatten_kind: Literal["node", "file"] = "node"
    output_target: OutputTarget = field(default_factory=OutputTarget)
    log_level: Literal["INFO", "DEBUG"] = "INFO"
    fail_fast: bool = False


@dataclass(frozen=True)
class AnalysisStats:
    total_files: int
    ok_files: int
    failed_files: int
    skipped_files: int
    emitted_records: int | None = None
    emitted_documents: int | None = None


@dataclass(frozen=True)
class AnalysisResult:
    parsed_files: list[ParsedFile]
    skipped_files: list[SkippedFile]
    stats: AnalysisStats
    stopped_early: bool = False


@dataclass(frozen=True)
class AstProjection:
    schema_version: str
    json_payload: dict[str, Any]
    ndjson_records: list[dict[str, Any]]


@dataclass(frozen=True)
class CodeUnitsProjection:
    schema_version: str
    json_payload: dict[str, Any]
