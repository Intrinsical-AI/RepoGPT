from __future__ import annotations

import re
from typing import Any


def validate_top_k(top_k: int) -> None:
    if type(top_k) is not int or top_k < 0:
        raise ValueError("top_k must be an integer >= 0")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def _retrievable(document: dict[str, Any]) -> bool:
    return document.get("unit_type") != "module" or bool(str(document.get("content", "")).strip())


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
    query_symbol = query_text.strip().lower()

    def score(document: dict[str, Any]) -> int:
        search_tokens = _tokenize(_document_search_text(document))
        overlap = len(query_tokens & search_tokens)
        symbol = document.get("symbol")
        exact_symbol_match = bool(
            query_symbol and isinstance(symbol, str) and symbol.lower() == query_symbol
        )
        return overlap + exact_symbol_match * 2

    scored = [(score(document), document) for document in documents if _retrievable(document)]
    return [
        document
        for rank, document in sorted(
            scored,
            key=lambda item: (
                -item[0],
                len(str(item[1].get("qualified_name", ""))),
                str(item[1].get("external_id", "")),
            ),
        )
        if rank > 0
    ]


def assemble_flat_bundle(
    documents: list[dict[str, Any]],
    *,
    query_text: str,
    top_k: int = 3,
) -> dict[str, Any]:
    validate_top_k(top_k)
    ranked = rank_documents(documents, query_text)
    items = ranked[:top_k]
    return {
        "profile": "flat_rag_v2",
        "query_text": query_text,
        "seed_count": len(items),
        "expanded_count": 0,
        "estimated_tokens": _estimate_tokens(items),
        "items": items,
    }


def _expand_bundle(
    documents: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
    *,
    query_text: str,
) -> dict[str, Any]:
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
        if container is None or not _retrievable(container):
            continue
        if container_id in seen:
            continue
        seen.add(container_id)
        items.append(container)

    return {
        "profile": "structured_rag_v2",
        "query_text": query_text,
        "seed_count": len(seeds),
        "expanded_count": max(0, len(items) - len(seeds)),
        "estimated_tokens": _estimate_tokens(items),
        "items": items,
    }


def compare_profiles(
    documents: list[dict[str, Any]],
    *,
    query_text: str,
    top_k: int = 3,
) -> dict[str, Any]:
    flat = assemble_flat_bundle(documents, query_text=query_text, top_k=top_k)
    structured = _expand_bundle(documents, flat["items"], query_text=query_text)
    return {
        "query_text": query_text,
        "top_k": top_k,
        **{
            bundle["profile"]: {
                "seed_count": bundle["seed_count"],
                "expanded_count": bundle["expanded_count"],
                "estimated_tokens": bundle["estimated_tokens"],
                "external_ids": [item["external_id"] for item in bundle["items"]],
            }
            for bundle in (flat, structured)
        },
    }
