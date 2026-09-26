from __future__ import annotations

import re

from repogpt.domain.analysis import AnalysisRequest, AnalysisResult, CodeUnitsProjection
from repogpt.domain.errors import InvalidRequestError, UnsafeReplacementError

REPO_KEY_PATTERN = r"[a-z0-9][a-z0-9._-]{0,127}"


def validate_request(request: AnalysisRequest, supported_extensions: set[str]) -> None:
    if request.repo_key is not None and re.fullmatch(REPO_KEY_PATTERN, request.repo_key) is None:
        raise InvalidRequestError(f"repo_key must match {REPO_KEY_PATTERN}")
    if request.projection != "code_units" and (
        request.repo_key is not None or request.replace_scope
    ):
        raise InvalidRequestError("repo_key and replace_scope require code-units emission")
    if request.projection == "code_units" and request.format != "json":
        raise InvalidRequestError("code-units only supports JSON")
    if request.replace_scope:
        languages = (
            set(request.supported_languages)
            if request.supported_languages is not None
            else supported_extensions
        )
        if languages != supported_extensions or not request.include_tests:
            raise InvalidRequestError(
                "replace_scope requires all supported languages and include_tests=true"
            )


def validate_replacement(result: AnalysisResult, projection: CodeUnitsProjection) -> None:
    guarded_paths = [
        item.relative_path
        for item in result.skipped_files
        if item.reason in {"file_too_large", "binary_file"}
    ]
    if (
        result.stopped_early
        or result.stats.failed_files
        or not projection.json_payload["documents"]
        or guarded_paths
    ):
        detail = f"; omitted candidates: {', '.join(guarded_paths[:5])}" if guarded_paths else ""
        raise UnsafeReplacementError(
            "replace_scope requires a complete, non-empty export without failures" + detail
        )
