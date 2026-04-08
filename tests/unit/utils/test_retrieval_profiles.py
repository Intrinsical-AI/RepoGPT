from __future__ import annotations

from repogpt.utils.retrieval_profiles import (
    compare_profiles,
    assemble_flat_bundle,
    assemble_structured_bundle,
    rank_documents,
)


def _documents() -> list[dict[str, object]]:
    return [
        {
            "external_id": "repogpt:demo:sample.py:class:Demo",
            "container_id": "repogpt:demo:sample.py:module",
            "symbol": "Demo",
            "qualified_name": "Demo",
            "path": "sample.py",
            "content": (
                "class Demo:\n    def method(self, value: int) -> int:\n        return value\n"
            ),
        },
        {
            "external_id": "repogpt:demo:sample.py:method:Demo.method",
            "container_id": "repogpt:demo:sample.py:class:Demo",
            "symbol": "method",
            "qualified_name": "Demo.method",
            "path": "sample.py",
            "content": "def method(self, value: int) -> int:\n    return value\n",
        },
        {
            "external_id": "repogpt:demo:sample.py:function:helper",
            "container_id": "repogpt:demo:sample.py:module",
            "symbol": "helper",
            "qualified_name": "helper",
            "path": "sample.py",
            "content": "def helper(name: str = 'world') -> str:\n    return name\n",
        },
    ]


def test_rank_documents_prefers_exact_symbol_match() -> None:
    ranked = rank_documents(_documents(), "helper")

    assert ranked[0]["external_id"] == "repogpt:demo:sample.py:function:helper"


def test_flat_bundle_returns_top_k_without_expansion() -> None:
    bundle = assemble_flat_bundle(_documents(), query_text="method", top_k=1)

    assert bundle["profile"] == "flat_rag_v1"
    assert bundle["seed_count"] == 1
    assert bundle["expanded_count"] == 0
    assert [item["external_id"] for item in bundle["items"]] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]


def test_structured_bundle_adds_available_container_documents() -> None:
    bundle = assemble_structured_bundle(_documents(), query_text="method", top_k=1)

    assert bundle["profile"] == "structured_rag_v1"
    assert bundle["seed_count"] == 1
    assert bundle["expanded_count"] == 1
    assert [item["external_id"] for item in bundle["items"]] == [
        "repogpt:demo:sample.py:method:Demo.method",
        "repogpt:demo:sample.py:class:Demo",
    ]


def test_compare_profiles_returns_both_profile_summaries() -> None:
    comparison = compare_profiles(_documents(), query_text="method", top_k=1)

    assert comparison["query_text"] == "method"
    assert comparison["top_k"] == 1
    assert comparison["flat_rag_v1"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]
    assert comparison["structured_rag_v1"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method",
        "repogpt:demo:sample.py:class:Demo",
    ]
