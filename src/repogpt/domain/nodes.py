from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NodeId = str


@dataclass
class CodeNode:
    id: NodeId
    type: str
    name: str | None = None
    language: str | None = None
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    docstring: str | None = None
    comments: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    parent_id: NodeId | None = None
    children: list[CodeNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.type}:{self.name} @{self.start_line}-{self.end_line}>"
