import time
from collections.abc import Callable
from typing import Any
from repogpt.models import CodeNode
from repogpt.utils.tree_utils import (
    nodes_by_type,
    all_comments,
    all_docstrings,
    all_tags,
    nodes_where,
    iter_nodes,
)


def build_tree(depth: int, width: int, id_prefix: str = "node") -> CodeNode:
    node = CodeNode(
        id=id_prefix,
        type="function",
        name=f"func_{id_prefix}",
        docstring=f"Docstring for {id_prefix}" if depth % 2 == 0 else None,
        comments=[{"text": "A comment", "line": 1}] if depth % 3 == 0 else [],
        tags=["tag1", "tag2"] if depth % 4 == 0 else [],
    )
    if depth > 0:
        for i in range(width):
            child = build_tree(depth - 1, width, f"{id_prefix}_{i}")
            child.parent_id = node.id
            node.children.append(child)
    return node


def benchmark_function(func: Callable[..., Any], *args: Any, iterations: int = 10) -> float:
    start_time = time.perf_counter()
    for _ in range(iterations):
        func(*args)
    end_time = time.perf_counter()
    return (end_time - start_time) / iterations


if __name__ == "__main__":
    print("Building tree...")
    # Depth 6, width 4 -> 1 + 4 + 16 + 64 + 256 + 1024 + 4096
    root = build_tree(7, 3)
    num_nodes = len(iter_nodes(root))
    print(f"Tree built with {num_nodes} nodes.")

    print("\nBenchmarking...")
    t_nodes_by_type = benchmark_function(nodes_by_type, root, "function")
    print(f"nodes_by_type: {t_nodes_by_type:.6f} seconds")

    t_all_comments = benchmark_function(all_comments, root)
    print(f"all_comments: {t_all_comments:.6f} seconds")

    t_all_docstrings = benchmark_function(all_docstrings, root)
    print(f"all_docstrings: {t_all_docstrings:.6f} seconds")

    t_all_tags = benchmark_function(all_tags, root)
    print(f"all_tags: {t_all_tags:.6f} seconds")

    t_nodes_where = benchmark_function(nodes_where, root, lambda n: n.type == "function")
    print(f"nodes_where: {t_nodes_where:.6f} seconds")
