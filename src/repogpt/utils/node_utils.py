from __future__ import annotations

import hashlib


def stable_node_id(
    *,
    path: str,
    type_: str,
    name: str | None,
    start_line: int | None,
    end_line: int | None,
    parent_id: str | None,
) -> str:
    raw = "|".join(
        [
            path,
            type_,
            name or "",
            "" if start_line is None else str(start_line),
            "" if end_line is None else str(end_line),
            parent_id or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
