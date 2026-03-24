from __future__ import annotations

import re
from typing import Any


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if token}


def _document_search_text(document: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in (
            document.get("symbol", ""),
            document.get("qualified_name", ""),
            document.get("path", ""),
            document.get("content", ""),
        )
        if part
    )


def _estimate_tokens(documents: list[dict[str, Any]]) -> int:
    total_chars = sum(len(str(document.get("content", ""))) for document in documents)
    return max(1, total_chars // 4) if documents else 0


def rank_documents(documents: list[dict[str, Any]], query_text: str) -> list[dict[str, Any]]:
    query_tokens = _tokenize(query_text)

    def score(document: dict[str, Any]) -> tuple[int, int, str]:
        search_tokens = _tokenize(_document_search_text(document))
        overlap = len(query_tokens & search_tokens)
        exact_symbol_match = int(str(document.get("symbol", "")).lower() == query_text.lower())
        return (
            overlap + exact_symbol_match * 2,
            len(str(document.get("qualified_name", ""))),
            str(document.get("external_id", "")),
        )

    return sorted(documents, key=score, reverse=True)


def assemble_flat_bundle(
    documents: list[dict[str, Any]],
    *,
    query_text: str,
    top_k: int = 3,
) -> dict[str, Any]:
    ranked = rank_documents(documents, query_text)
    items = ranked[:top_k]
    return {
        "profile": "flat_rag_v1",
        "query_text": query_text,
        "seed_count": len(items),
        "expanded_count": 0,
        "estimated_tokens": _estimate_tokens(items),
        "items": items,
    }


def assemble_structured_bundle(
    documents: list[dict[str, Any]],
    *,
    query_text: str,
    top_k: int = 3,
) -> dict[str, Any]:
    ranked = rank_documents(documents, query_text)
    seeds = ranked[:top_k]
    by_external_id = {
        str(document.get("external_id")): document
        for document in documents
        if document.get("external_id")
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for seed in seeds:
        external_id = str(seed.get("external_id", ""))
        if external_id and external_id not in seen:
            seen.add(external_id)
            items.append(seed)
        container_id = str(seed.get("container_id", ""))
        container = by_external_id.get(container_id)
        if container is None:
            continue
        if container_id in seen:
            continue
        seen.add(container_id)
        items.append(container)

    return {
        "profile": "structured_rag_v1",
        "query_text": query_text,
        "seed_count": len(seeds),
        "expanded_count": max(0, len(items) - len(seeds)),
        "estimated_tokens": _estimate_tokens(items),
        "items": items,
    }
