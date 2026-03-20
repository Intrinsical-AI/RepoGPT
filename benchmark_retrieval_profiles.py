from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from repogpt.utils.retrieval_profiles import assemble_flat_bundle, assemble_structured_bundle


def _load_documents(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("expected a code-units payload with a documents array")
    return [document for document in documents if isinstance(document, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare flat_rag_v1 and structured_rag_v1 on a code-units artifact.",
    )
    parser.add_argument("artifact", help="Path to a code-units JSON artifact")
    parser.add_argument("query", help="Query text to evaluate")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    documents = _load_documents(Path(args.artifact))
    flat = assemble_flat_bundle(documents, query_text=args.query, top_k=args.top_k)
    structured = assemble_structured_bundle(documents, query_text=args.query, top_k=args.top_k)

    print(
        json.dumps(
            {
                "query_text": args.query,
                "top_k": args.top_k,
                "flat_rag_v1": {
                    "seed_count": flat["seed_count"],
                    "expanded_count": flat["expanded_count"],
                    "estimated_tokens": flat["estimated_tokens"],
                    "external_ids": [item["external_id"] for item in flat["items"]],
                },
                "structured_rag_v1": {
                    "seed_count": structured["seed_count"],
                    "expanded_count": structured["expanded_count"],
                    "estimated_tokens": structured["estimated_tokens"],
                    "external_ids": [item["external_id"] for item in structured["items"]],
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
