from __future__ import annotations

from repogpt.models import CodeNode
from repogpt.utils.tree_utils import flatten_tree, iter_nodes


def _deep_tree(depth: int) -> CodeNode:
    root = CodeNode(id="root", type="module", name="root", language="py", path="root.py")
    current = root
    for index in range(depth):
        child = CodeNode(
            id=f"node-{index}",
            type="class",
            name=f"Node{index}",
            language="py",
            path="root.py",
        )
        current.children.append(child)
        current = child
    return root


def test_iter_nodes_handles_deep_trees_without_recursion_error() -> None:
    root = _deep_tree(1500)

    nodes = iter_nodes(root)

    assert len(nodes) == 1501
    assert nodes[0].id == "root"
    assert nodes[-1].id == "node-1499"


def test_flatten_tree_preserves_preorder_for_deep_trees() -> None:
    root = _deep_tree(5)

    nodes = flatten_tree(root)

    assert [node["id"] for node in nodes] == [
        "root",
        "node-0",
        "node-1",
        "node-2",
        "node-3",
        "node-4",
    ]
