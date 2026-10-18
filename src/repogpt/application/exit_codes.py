from __future__ import annotations

from repogpt.domain.analysis import AnalysisResult

EXIT_SUCCESS = 0
EXIT_FAIL_FAST = 1
EXIT_PARTIAL_FAILURE = 2
EXIT_OPERATIONAL_ERROR = 3


def exit_code_for_result(result: AnalysisResult) -> int:
    if result.stopped_early:
        return EXIT_FAIL_FAST
    if result.stats.failed_files > 0:
        return EXIT_PARTIAL_FAILURE
    return EXIT_SUCCESS
