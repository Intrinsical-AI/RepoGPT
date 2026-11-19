from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from repogpt.utils.text_processing import physical_lines

FLAT_PROFILE = "flat_rag_v3"
STRUCTURED_PROFILE = "structured_rag_v3"
SourceKey = tuple[str, str, str, str, str]


@dataclass
class _ContextSource:
    key: SourceKey
    lines: dict[int, str] = field(default_factory=dict)
    owners: dict[int, set[str]] = field(default_factory=dict)
    external_ids: list[str] = field(default_factory=list)


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


def _context_text(document: dict[str, Any], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid context {name}: expected a non-empty string")
    return value


def _context_source_key(document: dict[str, Any]) -> SourceKey:
    metadata = document.get("metadata")
    file = metadata.get("file") if isinstance(metadata, dict) else None
    digest = file.get("sha256") if isinstance(file, dict) else None
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid context metadata.file.sha256")
    return (
        _context_text(document, "scope"),
        _context_text(document, "snapshot_id"),
        _context_text(document, "source_id"),
        _context_text(document, "path"),
        digest,
    )


def _context_line(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("Invalid context source coordinate: expected a positive integer")
    return value


def _context_document_lines(document: dict[str, Any]) -> list[tuple[int, str]]:
    start = _context_line(document.get("start_line"))
    end = _context_line(document.get("end_line"))
    if end < start:
        raise ValueError("Invalid context source span: end precedes start")
    content = document.get("content")
    if not isinstance(content, str):
        raise ValueError("Invalid context content: expected a string")
    lines = physical_lines(content, keepends=True)
    raw_ranges = document.get("content_ranges")
    if _context_text(document, "unit_type") == "module":
        if not isinstance(raw_ranges, list):
            raise ValueError("Invalid context module content_ranges: expected an array")
    else:
        if raw_ranges is not None:
            raise ValueError("Invalid context content_ranges: only modules have residual ranges")
        raw_ranges = [{"start_line": start, "end_line": end}]
    ranges: list[tuple[int, int]] = []
    previous_end = 0
    for interval in raw_ranges:
        if not isinstance(interval, dict):
            raise ValueError("Invalid context content_ranges entry")
        first = _context_line(interval.get("start_line"))
        last = _context_line(interval.get("end_line"))
        if not start <= first <= last <= end or first <= previous_end:
            raise ValueError(
                "Invalid context content_ranges: unordered, overlapping, or out of bounds"
            )
        ranges.append((first, last))
        previous_end = last
    if sum(last - first + 1 for first, last in ranges) != len(lines):
        raise ValueError("Invalid context content: source ranges do not match physical lines")
    positions = [number for first, last in ranges for number in range(first, last + 1)]
    return list(zip(positions, lines, strict=True))


def _context_sources(items: list[dict[str, Any]]) -> list[_ContextSource]:
    sources: dict[SourceKey, _ContextSource] = {}
    for document in items:
        key = _context_source_key(document)
        source = sources.setdefault(key, _ContextSource(key))
        external_id = _context_text(document, "external_id")
        if external_id not in source.external_ids:
            source.external_ids.append(external_id)
        for number, text in _context_document_lines(document):
            previous = source.lines.get(number)
            if previous is not None and previous != text:
                raise ValueError(f"Conflicting context source line {key[3]}:{number}")
            source.lines[number] = text
            source.owners.setdefault(number, set()).add(external_id)
    for source in sources.values():
        last_line = max(source.lines, default=0)
        if any(
            number < last_line and not text.endswith(("\n", "\r"))
            for number, text in source.lines.items()
        ):
            raise ValueError("Invalid context physical line: missing newline before a later line")
    return list(sources.values())


def _context_intervals(source: _ContextSource) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    for number in sorted(source.lines):
        if intervals and number == intervals[-1][1] + 1:
            intervals[-1] = intervals[-1][0], number
        else:
            intervals.append((number, number))
    return intervals


def _assemble_context(items: list[dict[str, Any]]) -> dict[str, Any]:
    text_parts: list[str] = []
    segments: list[dict[str, Any]] = []
    offset = 0
    for source in _context_sources(items):
        scope, snapshot_id, source_id, path, file_hash = source.key
        for start, end in _context_intervals(source):
            header = (
                json.dumps(
                    {
                        "source_id": source_id,
                        "snapshot_id": snapshot_id,
                        "path": path,
                        "start_line": start,
                        "end_line": end,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            separator = "\n\n" if text_parts else ""
            content = "".join(source.lines[number] for number in range(start, end + 1))
            owners = {owner for number in range(start, end + 1) for owner in source.owners[number]}
            offset += len(separator) + len(header)
            segments.append(
                {
                    "scope": scope,
                    "snapshot_id": snapshot_id,
                    "source_id": source_id,
                    "path": path,
                    "file_sha256": file_hash,
                    "start_line": start,
                    "end_line": end,
                    "text_start": offset,
                    "text_end": offset + len(content),
                    "external_ids": [key for key in source.external_ids if key in owners],
                }
            )
            text_parts.extend((separator, header, content))
            offset += len(content)
    return {"text": "".join(text_parts), "segments": segments}


def _bundle(
    items: list[dict[str, Any]], *, profile: str, query_text: str, seed_count: int
) -> dict[str, Any]:
    context = _assemble_context(items)
    characters = len(context["text"])
    return {
        "profile": profile,
        "query_text": query_text,
        "seed_count": seed_count,
        "expanded_count": max(0, len(items) - seed_count),
        "items": items,
        "context": context,
        "context_characters": characters,
        "context_segment_count": len(context["segments"]),
        "estimated_tokens": (characters + 3) // 4,
    }


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
    return _bundle(items, profile=FLAT_PROFILE, query_text=query_text, seed_count=len(items))


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

    return _bundle(items, profile=STRUCTURED_PROFILE, query_text=query_text, seed_count=len(seeds))


def assemble_structured_bundle(
    documents: list[dict[str, Any]],
    *,
    query_text: str,
    top_k: int = 3,
) -> dict[str, Any]:
    validate_top_k(top_k)
    seeds = rank_documents(documents, query_text)[:top_k]
    return _expand_bundle(documents, seeds, query_text=query_text)


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
                "context_characters": bundle["context_characters"],
                "context_segment_count": bundle["context_segment_count"],
                "external_ids": [item["external_id"] for item in bundle["items"]],
            }
            for bundle in (flat, structured)
        },
    }
