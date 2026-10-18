from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import repogpt.utils.retrieval_profiles as retrieval_profiles
from repogpt.domain.analysis import AnalysisRequest
from repogpt.runtime import build_analyze_repo
from repogpt.utils.retrieval_profiles import (
    _expand_bundle,
    assemble_flat_bundle,
    compare_profiles,
    rank_documents,
)


def _document(**overrides: Any) -> dict[str, Any]:
    return {
        "external_id": "one",
        "container_id": "missing-module",
        "scope": "repogpt:demo",
        "snapshot_id": "demo-snapshot",
        "source_id": "repogpt:demo:file:sample.py",
        "path": "sample.py",
        "unit_type": "function",
        "qualified_name": "one",
        "symbol": "needle",
        "start_line": 1,
        "end_line": 1,
        "content": "needle\n",
        "metadata": {"file": {"sha256": "a" * 64}},
        **overrides,
    }


def _documents() -> list[dict[str, Any]]:
    documents = [
        {
            "external_id": "repogpt:demo:sample.py:class:Demo",
            "container_id": "repogpt:demo:sample.py:module",
            "symbol": "Demo",
            "qualified_name": "Demo",
            "path": "sample.py",
            "unit_type": "class",
            "start_line": 1,
            "end_line": 3,
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
            "unit_type": "method",
            "start_line": 2,
            "end_line": 3,
            "content": "    def method(self, value: int) -> int:\n        return value\n",
        },
        {
            "external_id": "repogpt:demo:sample.py:function:helper",
            "container_id": "repogpt:demo:sample.py:module",
            "symbol": "helper",
            "qualified_name": "helper",
            "path": "sample.py",
            "start_line": 5,
            "end_line": 6,
            "content": "def helper(name: str = 'world') -> str:\n    return name\n",
        },
    ]
    return [_document(**document) for document in documents]


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
    module = _document(
        **{
            "external_id": "module",
            "container_id": "module",
            "unit_type": "module",
            "symbol": "sample",
            "qualified_name": "sample.py",
            "path": "sample.py",
            "content": " \n",
        }
    )
    function = _document(
        **{
            "external_id": "function",
            "container_id": "module",
            "unit_type": "function",
            "symbol": "f",
            "qualified_name": "f",
            "path": "sample.py",
            "content": "def f(): pass\n",
        }
    )
    assert [doc["external_id"] for doc in rank_documents([module, function], "sample")] == [
        "function"
    ]
    structured = compare_profiles([module, function], query_text="f", top_k=1)["structured_rag_v3"]
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

    assert bundle["profile"] == "flat_rag_v3"
    assert bundle["seed_count"] == 1
    assert bundle["expanded_count"] == 0
    assert [item["external_id"] for item in bundle["items"]] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]


def test_structured_bundle_adds_available_container_documents() -> None:
    bundle = compare_profiles(_documents(), query_text="method", top_k=1)["structured_rag_v3"]

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
    assert comparison["flat_rag_v3"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method"
    ]
    assert comparison["structured_rag_v3"]["external_ids"] == [
        "repogpt:demo:sample.py:method:Demo.method",
        "repogpt:demo:sample.py:class:Demo",
    ]


def _source_contents(bundle: dict[str, Any]) -> list[str]:
    context = bundle["context"]
    return [
        context["text"][segment["text_start"] : segment["text_end"]]
        for segment in context["segments"]
    ]


def test_context_deduplicates_nested_source_without_mutating_selected_documents() -> None:
    documents = _documents()
    original = deepcopy(documents)
    method, parent = documents[1], documents[0]
    bundle = _expand_bundle(documents, [method], query_text="method")

    assert bundle["items"] == [method, parent]
    assert bundle["items"][0] is method
    assert documents == original
    assert _source_contents(bundle) == [parent["content"]]
    segment = bundle["context"]["segments"][0]
    assert (segment["start_line"], segment["end_line"]) == (1, 3)
    assert segment["external_ids"] == [method["external_id"], parent["external_id"]]
    text = bundle["context"]["text"]
    assert text.count("def method") == 1
    assert bundle["context_characters"] == len(text)
    assert bundle["context_segment_count"] == 1
    assert bundle["estimated_tokens"] == (len(text) + 3) // 4


def test_public_structured_context_deduplicates_a_real_nested_export(tmp_path: Path) -> None:
    content = 'class Demo:\n    def method(self):\n        return "unique_method_context"\n'
    (tmp_path / "sample.py").write_text(content, encoding="utf-8")
    _, projection = build_analyze_repo().run(
        AnalysisRequest(repo_root=tmp_path, projection="code_units")
    )
    documents = projection.json_payload["documents"]
    original = deepcopy(documents)
    bundle = retrieval_profiles.assemble_structured_bundle(documents, query_text="method", top_k=1)

    assert bundle["profile"] == "structured_rag_v3"
    assert bundle["seed_count"] == bundle["expanded_count"] == 1
    assert [item["unit_type"] for item in bundle["items"]] == ["method", "class"]
    assert all(any(item is document for document in documents) for item in bundle["items"])
    assert documents == original
    assert _source_contents(bundle) == [content]
    assert bundle["context"]["text"].count('return "unique_method_context"') == 1


def test_flat_context_deduplicates_partially_overlapping_and_adjacent_spans() -> None:
    documents = [
        _document(external_id="first", start_line=2, end_line=3, content="needle two\nthree\n"),
        _document(external_id="second", start_line=3, end_line=4, content="three\nfour\n"),
        _document(external_id="third", start_line=5, end_line=5, content="five\n"),
    ]
    bundle = assemble_flat_bundle(documents, query_text="needle", top_k=3)
    assert _source_contents(bundle) == ["needle two\nthree\nfour\nfive\n"]
    assert bundle["context"]["segments"][0]["external_ids"] == ["first", "second", "third"]


def test_module_context_maps_residual_ranges_instead_of_whole_file_bounds() -> None:
    module = _document(
        external_id="module",
        container_id="module",
        unit_type="module",
        start_line=1,
        end_line=9,
        content="preamble\nneedle between\ntail",
        content_ranges=[
            {"start_line": 1, "end_line": 1},
            {"start_line": 5, "end_line": 5},
            {"start_line": 9, "end_line": 9},
        ],
    )
    function = _document(start_line=2, end_line=3, content="def needle():\n    return 1\n")
    bundle = _expand_bundle([module, function], [function, module], query_text="needle")
    assert _source_contents(bundle) == [
        "preamble\ndef needle():\n    return 1\n",
        "needle between\n",
        "tail",
    ]
    assert [(s["start_line"], s["end_line"]) for s in bundle["context"]["segments"]] == [
        (1, 3),
        (5, 5),
        (9, 9),
    ]


@pytest.mark.parametrize("field", ["scope", "snapshot_id", "source_id", "path", "file_hash"])
def test_context_never_deduplicates_different_source_identities(field: str) -> None:
    first = _document(external_id="first")
    other = deepcopy(first)
    other["external_id"] = "other"
    if field == "file_hash":
        other["metadata"]["file"]["sha256"] = "b" * 64
    else:
        other[field] += "-different"
    bundle = _expand_bundle([first, other], [first, other], query_text="needle")
    assert _source_contents(bundle) == ["needle\n", "needle\n"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_context_preserves_physical_newlines_and_non_newline_unicode(newline: str) -> None:
    content = f"needle\u2028inline{newline}last line"
    bundle = assemble_flat_bundle([_document(content=content, end_line=2)], query_text="needle")
    assert _source_contents(bundle) == [content]


def test_context_orders_files_by_first_selected_item_then_source_lines() -> None:
    first = _document(external_id="later", start_line=8, end_line=8, content="later\n")
    second = _document(external_id="other", source_id="other", path="other.py")
    third = _document(external_id="earlier", start_line=1, end_line=1, content="earlier\n")
    bundle = _expand_bundle([first, second, third], [first, second, third], query_text="needle")
    assert _source_contents(bundle) == ["earlier\n", "later\n", "needle\n"]
    assert bundle == _expand_bundle(
        [first, second, third], [first, second, third], query_text="needle"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"start_line": None},
        {"start_line": True},
        {"start_line": 0},
        {"end_line": 0},
        {"end_line": 2},
        {"scope": ""},
        {"source_id": None},
        {"snapshot_id": ""},
        {"metadata": {}},
        {"metadata": {"file": {"sha256": "invalid"}}},
        {"content_ranges": [{"start_line": 1, "end_line": 1}]},
        {"unit_type": "module", "content_ranges": None},
        {"unit_type": "module", "content_ranges": []},
        {"unit_type": "module", "content_ranges": [{"start_line": 2, "end_line": 2}]},
        {"unit_type": "module", "content_ranges": [{"start_line": 1, "end_line": True}]},
        {"unit_type": "module", "content_ranges": [{"start_line": 1, "end_line": 1}] * 2},
    ],
)
def test_context_rejects_incomplete_or_invalid_source_coordinates(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="context"):
        assemble_flat_bundle([_document(**overrides)], query_text="needle")


def test_context_rejects_disagreement_on_overlapping_source_lines() -> None:
    first = _document(external_id="first", content="needle\n")
    second = _document(external_id="second", content="different\n")
    with pytest.raises(ValueError, match="Conflicting context source line"):
        _expand_bundle([first, second], [first, second], query_text="needle")


def test_context_rejects_an_unterminated_line_before_a_later_source_line() -> None:
    first = _document(external_id="first", content="needle")
    second = _document(external_id="second", start_line=2, end_line=2, content="later\n")
    with pytest.raises(ValueError, match="context physical line"):
        _expand_bundle([first, second], [first, second], query_text="needle")


def test_shared_container_is_selected_once_and_context_owners_keep_seed_order() -> None:
    parent, method = _documents()[:2]
    parent["content"] += "    def other(self):\n        return 2\n"
    parent["end_line"] = 5
    other = _document(
        external_id="other",
        container_id=parent["external_id"],
        start_line=4,
        end_line=5,
        content="    def other(self):\n        return 2\n",
    )
    bundle = _expand_bundle([parent, method, other], [method, other], query_text="method")
    assert bundle["seed_count"] == 2
    assert bundle["expanded_count"] == 1
    assert _source_contents(bundle) == [parent["content"]]
    assert bundle["context"]["segments"][0]["external_ids"] == [
        method["external_id"],
        parent["external_id"],
        other["external_id"],
    ]


def test_empty_context_has_zero_counts() -> None:
    bundle = assemble_flat_bundle(_documents(), query_text="unmatched")
    assert bundle["context"] == {"text": "", "segments": []}
    assert (
        bundle["context_characters"]
        == bundle["context_segment_count"]
        == bundle["estimated_tokens"]
        == 0
    )
