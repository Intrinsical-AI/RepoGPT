from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.domain.nodes import CodeNode
from repogpt.utils.tree_utils import flatten_tree, iter_nodes


def build_balanced_tree(depth: int, width: int) -> CodeNode:
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="benchmark.py",
        start_line=1,
        end_line=max(1, depth * width * width),
    )
    frontier = [root]
    next_id = 1
    next_line = 2
    for level in range(depth):
        next_frontier: list[CodeNode] = []
        for parent in frontier:
            for child_index in range(width):
                node_type = "class" if level % 2 == 0 else "function"
                child = CodeNode(
                    id=f"node-{next_id}",
                    type=node_type,
                    name=f"{node_type}_{level}_{child_index}",
                    language="py",
                    path="benchmark.py",
                    start_line=next_line,
                    end_line=next_line,
                    parent_id=parent.id,
                )
                next_id += 1
                next_line += 1
                parent.children.append(child)
                next_frontier.append(child)
        frontier = next_frontier
    return root


def build_nested_tree(depth: int) -> CodeNode:
    root = CodeNode(
        id="root",
        type="module",
        name="root",
        language="py",
        path="nested.py",
        start_line=1,
        end_line=depth * 2,
    )
    current = root
    for index in range(1, depth + 1):
        child = CodeNode(
            id=f"node-{index}",
            type="class" if index % 2 else "function",
            name=f"node_{index}",
            language="py",
            path="nested.py",
            start_line=index,
            end_line=(depth * 2) - index,
            parent_id=current.id,
        )
        current.children.append(child)
        current = child
    return root


def build_comments(count: int, max_line: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for index in range(count):
        comments.append(
            {
                "text": f"comment {index}",
                "line": 1 + (index % max_line),
            }
        )
    return comments


def reset_comments(root: CodeNode) -> None:
    for node in iter_nodes(root):
        node.comments.clear()


def benchmark_function(func: Callable[..., Any], *args: Any, iterations: int = 10) -> float:
    start_time = time.perf_counter()
    for _ in range(iterations):
        func(*args)
    return (time.perf_counter() - start_time) / iterations


def benchmark_comment_association(
    parser: PythonParser,
    root: CodeNode,
    comments: list[dict[str, Any]],
    *,
    iterations: int = 10,
) -> float:
    def run() -> None:
        reset_comments(root)
        parser._associate_comments(root, comments)

    return benchmark_function(run, iterations=iterations)


def main() -> int:
    tree_root = build_balanced_tree(depth=6, width=4)
    nested_root = build_nested_tree(depth=800)
    parser = PythonParser()
    comments = build_comments(count=2_000, max_line=nested_root.end_line or 1)

    print("Balanced tree nodes:", len(iter_nodes(tree_root)))
    print("Nested tree depth:", len(iter_nodes(nested_root)))
    print("Synthetic comments:", len(comments))

    iter_nodes_time = benchmark_function(iter_nodes, tree_root, iterations=25)
    flatten_tree_time = benchmark_function(flatten_tree, tree_root, iterations=25)
    associate_comments_time = benchmark_comment_association(
        parser,
        nested_root,
        comments,
        iterations=25,
    )

    reset_comments(nested_root)
    parser._associate_comments(nested_root, comments)
    attached_comments = sum(len(node.comments) for node in iter_nodes(nested_root))

    print("\nBenchmark results")
    print(f"iter_nodes:           {iter_nodes_time:.6f} seconds")
    print(f"flatten_tree:         {flatten_tree_time:.6f} seconds")
    print(f"associate_comments:   {associate_comments_time:.6f} seconds")
    print(f"attached comments:    {attached_comments}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
