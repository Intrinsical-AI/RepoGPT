from __future__ import annotations

import ast
from collections.abc import Sequence
from typing import Any

import structlog

from repogpt.domain.files import LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.parsers import ParserPort
from repogpt.utils.node_utils import stable_node_id
from repogpt.utils.text_processing import count_blank_lines, extract_comments, physical_lines

logger = structlog.get_logger(__name__)


class PythonParser(ParserPort):
    def parse(self, loaded_file: LoadedFile) -> CodeNode:
        path = loaded_file.abs_path
        content = loaded_file.text
        tree = ast.parse(content, filename=str(path))
        relative_path = loaded_file.relative_path
        lines = physical_lines(content)
        total_lines = len(lines) or 1

        root = CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="module",
                name=path.stem,
                start_line=1,
                end_line=total_lines,
                parent_id=None,
            ),
            type="module",
            name=path.stem,
            language="py",
            path=relative_path,
            start_line=1,
            end_line=total_lines,
            docstring=ast.get_docstring(tree),
            metrics={
                "blank_lines": count_blank_lines(content),
                "non_empty_lines": sum(bool(line.strip()) for line in lines),
            },
            attributes={"relative_path": relative_path},
        )

        self._visit_sequence(tree.body, parent_node=root, relative_path=relative_path)
        self._associate_comments(root, extract_comments(content, language="python"))
        return root

    def _visit_sequence(
        self,
        nodes: Sequence[ast.stmt],
        *,
        parent_node: CodeNode,
        relative_path: str,
    ) -> None:
        for child in nodes:
            code_node = self._build_node(
                node=child,
                parent_node=parent_node,
                relative_path=relative_path,
            )
            if code_node is None:
                nested_parent = parent_node
            else:
                parent_node.children.append(code_node)
                nested_parent = code_node
            nested_nodes = self._block_statements(child)
            self._visit_sequence(
                nested_nodes, parent_node=nested_parent, relative_path=relative_path
            )

    def _block_statements(self, node: ast.AST) -> list[ast.stmt]:
        statements: list[ast.stmt] = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                statements.append(child)
            elif isinstance(child, ast.ExceptHandler | ast.match_case):
                statements.extend(self._block_statements(child))
        return sorted(statements, key=lambda statement: (statement.lineno, statement.col_offset))

    def _build_node(
        self,
        *,
        node: ast.stmt,
        parent_node: CodeNode,
        relative_path: str,
    ) -> CodeNode | None:
        if isinstance(node, ast.Import):
            return self._make_import_node(
                module=None,
                aliases=node.names,
                import_kind="import",
                import_level=0,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                col_offset=node.col_offset,
                parent_node=parent_node,
                relative_path=relative_path,
            )
        if isinstance(node, ast.ImportFrom):
            return self._make_import_node(
                module=node.module,
                aliases=node.names,
                import_kind="from",
                import_level=node.level,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                col_offset=node.col_offset,
                parent_node=parent_node,
                relative_path=relative_path,
            )
        if isinstance(node, ast.ClassDef):
            return self._make_class_node(
                node=node,
                parent_node=parent_node,
                relative_path=relative_path,
            )
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            return self._make_callable_node(
                node=node,
                parent_node=parent_node,
                relative_path=relative_path,
            )
        return None

    def _make_import_node(
        self,
        *,
        module: str | None,
        aliases: Sequence[ast.alias],
        import_kind: str,
        import_level: int,
        lineno: int,
        end_lineno: int,
        col_offset: int,
        parent_node: CodeNode,
        relative_path: str,
    ) -> CodeNode:
        imported_names: list[dict[str, Any]] = [
            {"name": alias.name, "asname": alias.asname} for alias in aliases
        ]
        attributes = {
            "module": module,
            "import_kind": import_kind,
            "is_relative": bool(import_level),
            "import_level": import_level,
            "imported_names": imported_names,
        }
        return CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="import",
                name=module or ",".join(alias.name for alias in aliases),
                start_line=lineno,
                end_line=end_lineno,
                parent_id=parent_node.id,
                start_column=col_offset,
            ),
            type="import",
            name=module or None,
            language="py",
            path=relative_path,
            parent_id=parent_node.id,
            start_line=lineno,
            end_line=end_lineno,
            attributes=attributes,
            dependencies=imported_names,
        )

    def _make_class_node(
        self,
        *,
        node: ast.ClassDef,
        parent_node: CodeNode,
        relative_path: str,
    ) -> CodeNode:
        return CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="class",
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent_id=parent_node.id,
            ),
            type="class",
            name=node.name,
            language="py",
            path=relative_path,
            parent_id=parent_node.id,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node),
            attributes={
                "bases": [self._expr_to_source(base) for base in node.bases],
                "decorators": [self._expr_to_source(dec) for dec in node.decorator_list],
            },
        )

    def _make_callable_node(
        self,
        *,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_node: CodeNode,
        relative_path: str,
    ) -> CodeNode:
        node_type = "method" if parent_node.type == "class" else "function"
        params = self._extract_params(node.args)
        returns = self._expr_to_source(node.returns)
        signature = f"{node.name}({ast.unparse(node.args)})"
        if returns:
            signature = f"{signature} -> {returns}"
        return CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_=node_type,
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                parent_id=parent_node.id,
            ),
            type=node_type,
            name=node.name,
            language="py",
            path=relative_path,
            parent_id=parent_node.id,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            docstring=ast.get_docstring(node),
            attributes={
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "decorators": [self._expr_to_source(dec) for dec in node.decorator_list],
                "params": params,
                "returns": returns,
                "visibility": self._visibility(node.name),
                "signature": signature,
            },
        )

    def _extract_params(self, args: ast.arguments) -> list[dict[str, Any]]:
        params: list[dict[str, Any]] = []
        positional = list(args.posonlyargs) + list(args.args)
        defaults_offset = len(positional) - len(args.defaults)
        for index, arg in enumerate(positional):
            default = None
            if index >= defaults_offset:
                default = self._expr_to_source(args.defaults[index - defaults_offset])
            params.append(
                {
                    "name": arg.arg,
                    "kind": ("positional_only" if index < len(args.posonlyargs) else "positional"),
                    "annotation": self._expr_to_source(arg.annotation),
                    "default": default,
                }
            )
        if args.vararg is not None:
            params.append(
                {
                    "name": args.vararg.arg,
                    "kind": "vararg",
                    "annotation": self._expr_to_source(args.vararg.annotation),
                    "default": None,
                }
            )
        for kwonly_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=False):
            default_value = self._expr_to_source(kw_default)
            params.append(
                {
                    "name": kwonly_arg.arg,
                    "kind": "keyword_only",
                    "annotation": self._expr_to_source(kwonly_arg.annotation),
                    "default": default_value,
                }
            )
        if args.kwarg is not None:
            params.append(
                {
                    "name": args.kwarg.arg,
                    "kind": "kwarg",
                    "annotation": self._expr_to_source(args.kwarg.annotation),
                    "default": None,
                }
            )
        return params

    def _expr_to_source(self, expr: ast.AST | None) -> str | None:
        if expr is None:
            return None
        try:
            return ast.unparse(expr)
        except Exception as exc:  # pragma: no cover
            logger.debug(
                "ast.unparse failed, annotation dropped",
                node_type=type(expr).__name__,
                error=str(exc),
            )
            return None

    def _visibility(self, name: str) -> str:
        if name.startswith("__") and not name.endswith("__"):
            return "private"
        if name.startswith("_"):
            return "protected"
        return "public"

    def _associate_comments(self, root: CodeNode, comments: list[dict[str, Any]]) -> None:
        for comment in comments:
            target = root
            stack = [root]
            while stack:
                node = stack.pop()
                if (
                    node.start_line is not None
                    and node.end_line is not None
                    and node.start_line <= comment["line"] <= node.end_line
                ):
                    target = node
                    stack.extend(reversed(node.children))
            target.comments.append(comment)
