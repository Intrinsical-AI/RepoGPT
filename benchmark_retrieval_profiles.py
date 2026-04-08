from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from repogpt.utils.retrieval_profiles import compare_profiles


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
    print(
        json.dumps(compare_profiles(documents, query_text=args.query, top_k=args.top_k), indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
