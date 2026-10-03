from __future__ import annotations

from repogpt.utils.retrieval_profiles import (
    assemble_flat_bundle,
    compare_profiles,
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


def test_no_positive_match_returns_no_documents() -> None:
    assert rank_documents(_documents(), "zzzqqq") == []
    assert assemble_flat_bundle(_documents(), query_text="zzzqqq", top_k=3)["items"] == []


def test_missing_symbol_does_not_match_none_query() -> None:
    documents = [
        {
            "external_id": "a",
            "container_id": "a",
            "symbol": None,
            "qualified_name": "something",
            "path": "sample.py",
            "content": "unrelated",
        }
    ]
    assert rank_documents(documents, "none") == []


def test_equal_scores_prefer_shorter_name_then_external_id() -> None:
    documents = [
        {"external_id": "b", "qualified_name": "a.long", "content": "needle"},
        {"external_id": "z", "qualified_name": "short", "content": "needle"},
        {"external_id": "a", "qualified_name": "short", "content": "needle"},
    ]
    assert [doc["external_id"] for doc in rank_documents(documents, "needle")] == ["a", "z", "b"]


def test_blank_structural_module_is_not_a_seed_or_expansion() -> None:
    module = {
        "external_id": "module",
        "container_id": "module",
        "unit_type": "module",
        "symbol": "sample",
        "qualified_name": "sample.py",
        "path": "sample.py",
        "content": " \n",
    }
    function = {
        "external_id": "function",
        "container_id": "module",
        "unit_type": "function",
        "symbol": "f",
        "qualified_name": "f",
        "path": "sample.py",
        "content": "def f(): pass\n",
    }
    assert [doc["external_id"] for doc in rank_documents([module, function], "sample")] == [
        "function"
    ]
    structured = compare_profiles([module, function], query_text="f", top_k=1)["structured_rag_v2"]
    assert structured["external_ids"] == ["function"]
    assert structured["expanded_count"] == 0


def test_meaningful_residual_module_is_retrievable() -> None:
    module = {
        "external_id": "module",
        "container_id": "module",
        "unit_type": "module",
        "symbol": "sample",
        "qualified_name": "sample.py",
        "path": "sample.py",
        "content": "CONSTANT = 3\n",
    }
    assert rank_documents([module], "constant") == [module]


def test_flat_bundle_returns_top_k_without_expansion() -> None:
    bundle = assemble_flat_bundle(_documents(), query_text="method", top_k=1)

    assert bundle["profile"] == "flat_rag_v2"
    assert bundle["seed_count"] == 1
    assert bundle["expanded_count"] == 0
    assert [item["external_id"] for item in bundle["items"]] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]


def test_structured_bundle_adds_available_container_documents() -> None:
    bundle = compare_profiles(_documents(), query_text="method", top_k=1)["structured_rag_v2"]

    assert bundle["seed_count"] == 1
    assert bundle["expanded_count"] == 1
    assert bundle["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method",
        "repogpt:demo:sample.py:class:Demo",
    ]


def test_compare_profiles_returns_both_profile_summaries() -> None:
    comparison = compare_profiles(_documents(), query_text="method", top_k=1)

    assert comparison["query_text"] == "method"
    assert comparison["top_k"] == 1
    assert comparison["flat_rag_v2"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]
    assert comparison["structured_rag_v2"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method",
        "repogpt:demo:sample.py:class:Demo",
    ]
