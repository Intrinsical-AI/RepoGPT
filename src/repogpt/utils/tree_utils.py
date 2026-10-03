from typing import Any

from repogpt.domain.nodes import CodeNode


def node_to_dict(node: CodeNode, *, recursive: bool = False) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": node.id,
        "type": node.type,
        "name": node.name,
        "language": node.language,
        "path": node.path,
        "start_line": node.start_line,
        "start_column": node.start_column,
        "end_line": node.end_line,
        "docstring": node.docstring,
        "comments": [dict(comment) for comment in node.comments],
        "tags": list(node.tags),
        "dependencies": [dict(dependency) for dependency in node.dependencies],
        "parent_id": node.parent_id,
    }
    if recursive:
        record["children"] = [node_to_dict(child, recursive=True) for child in node.children]
    record["attributes"] = dict(node.attributes)
    record["metrics"] = dict(node.metrics)
    return record


def flatten_tree(root: CodeNode) -> list[dict[str, Any]]:
    return [node_to_dict(node) for node in iter_nodes(root)]


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
