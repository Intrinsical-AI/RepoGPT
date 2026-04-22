from typing import Any

from repogpt.domain.nodes import CodeNode


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


def all_comments(root: CodeNode) -> list[dict[str, Any]]:
    """Devuelve todos los comentarios de todos los nodos."""
    return [dict(c) for n in iter_nodes(root) for c in n.comments]
