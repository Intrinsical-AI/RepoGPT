from __future__ import annotations

import hashlib
from pathlib import Path

from repogpt.adapters.projectors.ast_projector import AstProjector
from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, AnalysisStats
from repogpt.domain.errors import ParseFailure
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile, ParsedFile, SkippedFile
from repogpt.domain.nodes import CodeNode


def _loaded(path: str = "test.py", content: str = "x=1\n") -> LoadedFile:
    raw = content.encode("utf-8")
    return LoadedFile(
        collected_file=CollectedFile(abs_path=Path(path), relative_path=path, language="py"),
        raw_bytes=raw,
        text=content,
        digest=FileDigest(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
    )


def test_ast_projector_json_envelope() -> None:
    parsed_file = ParsedFile(
        loaded_file=_loaded(),
        root=CodeNode(
            id="node-1",
            type="module",
            name="test",
            language="py",
            path="test.py",
            start_line=1,
            end_line=1,
        ),
    )
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[],
        stats=AnalysisStats(total_files=1, ok_files=1, failed_files=0, skipped_files=0),
    )

    projection = AstProjector().project(result, AnalysisRequest(repo_root=Path.cwd()))

    assert projection.json_payload["schema_version"] == "1"
    assert projection.json_payload["failures"] == []
    assert projection.json_payload["records"][0]["record_type"] == "node"


def test_ast_projector_ndjson_contains_failure_and_summary() -> None:
    parsed_file = ParsedFile(
        loaded_file=_loaded(path="bad.py"),
        root=None,
        failure=ParseFailure("boom"),
    )
    result = AnalysisResult(
        parsed_files=[parsed_file],
        skipped_files=[
            SkippedFile(
                abs_path=Path("skip.py"),
                relative_path="skip.py",
                reason="ignored",
            )
        ],
        stats=AnalysisStats(total_files=1, ok_files=0, failed_files=1, skipped_files=1),
    )

    projection = AstProjector().project(result, AnalysisRequest(repo_root=Path.cwd()))

    assert [record["record_type"] for record in projection.ndjson_records] == ["failure", "summary"]
    assert projection.ndjson_records[1]["stats"]["failed_files"] == 1
