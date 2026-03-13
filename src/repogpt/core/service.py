from __future__ import annotations

import structlog

from repogpt.core.ports import CollectorPort, PipelinePort, PublisherPort
from repogpt.models import AnalysisConf

# === Service ===


class CodeRepoAnalysisService:
    def __init__(
        self, collector: CollectorPort, pipeline: PipelinePort, publisher: PublisherPort
    ):
        self.collector = collector
        self.pipeline = pipeline
        self.publisher = publisher
        self.log = structlog.get_logger(__name__)

    def run(self, runtime_conf: AnalysisConf) -> int:
        col = self.collector.collect(runtime_conf)
        results = []
        for path in col.files:
            result = self.pipeline.process(path, runtime_conf)
            results.append(result)
            if result.root is None and runtime_conf.fail_fast:
                self.log.error("aborting — fail-fast", first_error=result.error)
                return 1

        failed = [r for r in results if r.root is None]
        ok = len(results) - len(failed)
        self.log.info("pipeline finished", ok=ok, failed=len(failed))
        self.publisher.publish(results, runtime_conf)
        if failed:
            return 2
        return 0
