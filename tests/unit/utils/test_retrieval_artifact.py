from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repogpt.mcp_server import tool_compare_profiles
from repogpt.utils.retrieval_artifact import load_documents
from repogpt.utils.retrieval_profiles import (
    assemble_flat_bundle,
    assemble_structured_bundle,
    compare_profiles,
)


def _document() -> dict[str, Any]:
    return {
        "external_id": "one",
        "container_id": "root",
        "path": "sample.py",
        "qualified_name": "f",
        "symbol": "f",
        "content": "def f(): pass\n",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        {"documents": []},
        {"schema_version": "3", "kind": "code-units", "documents": []},
        {"schema_version": "4", "kind": "code-units", "documents": None},
    ],
)
def test_retrieval_rejects_invalid_envelope(tmp_path: Path, payload: Any) -> None:
    artifact = tmp_path / "input.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_documents(artifact)
    with pytest.raises(ValueError):
        tool_compare_profiles(str(artifact), "f")


@pytest.mark.parametrize(
    "documents",
    [
        [None],
        [_document(), "invalid"],
        [{**_document(), "external_id": ""}],
        [{**_document(), "container_id": 3}],
        [{**_document(), "content": None}],
        [{**_document(), "symbol": []}],
        [_document(), _document()],
    ],
)
def test_retrieval_never_discards_malformed_or_duplicate_documents(
    tmp_path: Path, documents: Any
) -> None:
    artifact = tmp_path / "input.json"
    artifact.write_text(
        json.dumps({"schema_version": "4", "kind": "code-units", "documents": documents}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_documents(artifact)


@pytest.mark.parametrize("top_k", [-1, True, "3", 1.5])
def test_top_k_validation_precedes_ranking(top_k: Any) -> None:
    with patch("repogpt.utils.retrieval_profiles.rank_documents") as rank:
        for assemble in (assemble_flat_bundle, assemble_structured_bundle, compare_profiles):
            with pytest.raises(ValueError, match="top_k"):
                assemble([_document()], query_text="f", top_k=top_k)
        rank.assert_not_called()


def test_zero_top_k_is_an_empty_bundle() -> None:
    comparison = compare_profiles([_document()], query_text="f", top_k=0)
    for name in ("flat_rag_v1", "structured_rag_v1"):
        assert comparison[name] == {
            "external_ids": [],
            "seed_count": 0,
            "expanded_count": 0,
            "estimated_tokens": 0,
        }
