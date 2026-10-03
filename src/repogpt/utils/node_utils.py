from __future__ import annotations

import hashlib
from typing import Any

from repogpt.domain.nodes import CodeNode


def stable_node_id(
    *,
    path: str,
    type_: str,
    start_line: int,
    start_column: int,
) -> str:
    raw = "|".join((path, type_, str(start_line), str(start_column)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def new_node(
    *, type_: str, path: str, start_line: int, start_column: int, **fields: Any
) -> CodeNode:
    return CodeNode(
        id=stable_node_id(path=path, type_=type_, start_line=start_line, start_column=start_column),
        type=type_,
        path=path,
        start_line=start_line,
        start_column=start_column,
        **fields,
    )
