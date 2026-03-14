from collections.abc import Callable
from typing import Any

from repogpt.models import CodeNode


def _node_to_dict(node: CodeNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type,
        "name": node.name,
        "language": node.language,
        "path": node.path,
        "start_line": node.start_line,
        "end_line": node.end_line,
        "docstring": node.docstring,
        "comments": [dict(comment) for comment in node.comments],
        "tags": list(node.tags),
        "dependencies": [
            dict(dependency) if isinstance(dependency, dict) else dependency
            for dependency in node.dependencies
        ],
        "parent_id": node.parent_id,
        "attributes": dict(node.attributes),
        "metrics": dict(node.metrics),
    }


def flatten_tree(root: CodeNode) -> list[dict[str, Any]]:
    return [_node_to_dict(node) for node in iter_nodes(root)]


def iter_nodes(root: CodeNode) -> list[CodeNode]:
    nodes: list[CodeNode] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(reversed(node.children))
    return nodes


# === Query-tree utils


def nodes_by_type(root: CodeNode, type_: str) -> list[dict[str, Any]]:
    """Devuelve todos los nodos del árbol de un tipo dado."""
    return [n for n in flatten_tree(root) if n["type"] == type_]


def all_comments(root: CodeNode) -> list[dict[str, Any]]:
    """Devuelve todos los comentarios de todos los nodos."""
    return [c for n in flatten_tree(root) for c in n.get("comments", [])]


def all_docstrings(root: CodeNode) -> list[str | None]:
    """Devuelve todos los docstrings de los nodos (si existen)."""
    return [n["docstring"] for n in flatten_tree(root) if n.get("docstring")]


def all_tags(root: CodeNode) -> list[str]:
    """Devuelve todos los tags de todos los nodos."""
    return [tag for n in flatten_tree(root) for tag in n.get("tags", [])]


# Avanzado: filtrado por predicado arbitrario
def nodes_where(
    root: CodeNode, predicate: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    """Devuelve nodos que cumplen una condición arbitraria."""
    return [n for n in flatten_tree(root) if predicate(n)]
