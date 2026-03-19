from __future__ import annotations

from repogpt.domain.analysis import AnalysisResult


def exit_code_for_result(result: AnalysisResult) -> int:
    if result.stopped_early and result.stats.failed_files > 0:
        return 1
    if result.stats.failed_files > 0:
        return 2
    return 0
