from __future__ import annotations

import argparse
import json
from pathlib import Path

from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import compare_profiles, validate_top_k


def _non_negative_int(value: str) -> int:
    number = int(value)
    validate_top_k(number)
    return number


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare flat_rag_v1 and structured_rag_v1 on a code-units artifact.",
    )
    parser.add_argument("artifact", help="Path to a code-units JSON artifact")
    parser.add_argument("query", help="Query text to evaluate")
    parser.add_argument("--top-k", type=_non_negative_int, default=3)
    args = parser.parse_args()

    try:
        documents = load_documents(Path(args.artifact))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(compare_profiles(documents, query_text=args.query, top_k=args.top_k), indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
