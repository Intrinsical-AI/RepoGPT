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
    """Return all nodes in DFS pre-order (root first, then children left-to-right).

    Uses an explicit stack to avoid recursion limits on deep trees.
    """
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
    return [_node_to_dict(n) for n in iter_nodes(root) if n.type == type_]


def all_comments(root: CodeNode) -> list[dict[str, Any]]:
    """Devuelve todos los comentarios de todos los nodos."""
    return [dict(c) for n in iter_nodes(root) for c in n.comments]


def all_docstrings(root: CodeNode) -> list[str | None]:
    """Devuelve todos los docstrings de los nodos (si existen)."""
    return [n.docstring for n in iter_nodes(root) if n.docstring]


def all_tags(root: CodeNode) -> list[str]:
    """Devuelve todos los tags de todos los nodos."""
    return [tag for n in iter_nodes(root) for tag in n.tags]


# Avanzado: filtrado por predicado arbitrario
def nodes_where(root: CodeNode, predicate: Callable[[CodeNode], bool]) -> list[dict[str, Any]]:
    """Devuelve nodos que cumplen una condición arbitraria."""
    return [_node_to_dict(n) for n in iter_nodes(root) if predicate(n)]
