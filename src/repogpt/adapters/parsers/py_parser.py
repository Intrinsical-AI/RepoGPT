from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Sequence
from typing import Any

import structlog

from repogpt.domain.files import LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.parsers import ParserPort
from repogpt.utils.node_utils import new_node
from repogpt.utils.text_processing import count_blank_lines, extract_comments, physical_lines

logger = structlog.get_logger(__name__)


def _character_column(line: str, byte_column: int) -> int:
    """Python AST columns count UTF-8 bytes; exported columns count characters."""
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))


def _decorator_origins(source_lines: list[str]) -> dict[tuple[int, int], tuple[int, int]]:
    """Map declaration keywords to the first decorator's actual @ token."""
    origins: dict[tuple[int, int], tuple[int, int]] = {}
    pending: tuple[int, int] | None = None
    statement_start = True
    # Normalize physical newlines for tokenize without changing line/character coordinates.
    for token in tokenize.generate_tokens(io.StringIO("\n".join(source_lines)).readline):
        if token.type == tokenize.NEWLINE:
            statement_start = True
        elif (
            token.type
            not in {
                tokenize.NL,
                tokenize.COMMENT,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENDMARKER,
            }
            and statement_start
        ):
            statement_start = False
            if token.type == tokenize.OP and token.string == "@":
                if pending is None:
                    pending = token.start
            else:
                if token.type == tokenize.NAME and token.string in {"def", "async", "class"}:
                    if pending is not None:
                        origins[token.start] = pending
                pending = None
    return origins


def _declaration_origin(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
    decorator_origins: dict[tuple[int, int], tuple[int, int]],
) -> tuple[int, int]:
    origin = node.lineno, _character_column(source_lines[node.lineno - 1], node.col_offset)
    return decorator_origins[origin] if node.decorator_list else origin


class PythonParser(ParserPort):
    def parse(self, loaded_file: LoadedFile) -> CodeNode:
        path = loaded_file.abs_path
        content = loaded_file.text
        tree = ast.parse(content, filename=loaded_file.relative_path)
        relative_path = loaded_file.relative_path
        lines = physical_lines(content)
        decorator_origins = _decorator_origins(lines)
        total_lines = len(lines) or 1

        root = new_node(
            type_="module",
            path=relative_path,
            start_line=1,
            start_column=0,
            name=path.stem,
            language="py",
            end_line=total_lines,
            docstring=ast.get_docstring(tree),
            metrics={
                "blank_lines": count_blank_lines(content),
                "non_empty_lines": sum(bool(line.strip()) for line in lines),
            },
            attributes={"relative_path": relative_path},
        )

        self._visit_sequence(
            tree.body,
            parent_node=root,
            relative_path=relative_path,
            source_lines=lines,
            decorator_origins=decorator_origins,
        )
        self._associate_comments(root, extract_comments(content, language="python"))
        return root

    def _visit_sequence(
        self,
        nodes: Sequence[ast.stmt],
        *,
        parent_node: CodeNode,
        relative_path: str,
        source_lines: list[str],
        decorator_origins: dict[tuple[int, int], tuple[int, int]],
    ) -> None:
        for child in nodes:
            code_node = self._build_node(
                node=child,
                parent_node=parent_node,
                relative_path=relative_path,
                source_lines=source_lines,
                decorator_origins=decorator_origins,
            )
            if code_node is None:
                nested_parent = parent_node
            else:
                parent_node.children.append(code_node)
                nested_parent = code_node
            nested_nodes = self._block_statements(child)
            self._visit_sequence(
                nested_nodes,
                parent_node=nested_parent,
                relative_path=relative_path,
                source_lines=source_lines,
                decorator_origins=decorator_origins,
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
        source_lines: list[str],
        decorator_origins: dict[tuple[int, int], tuple[int, int]],
    ) -> CodeNode | None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            return self._make_import_node(
                module=node.module if isinstance(node, ast.ImportFrom) else None,
                aliases=node.names,
                import_kind="from" if isinstance(node, ast.ImportFrom) else "import",
                import_level=node.level if isinstance(node, ast.ImportFrom) else 0,
                lineno=node.lineno,
                end_lineno=node.end_lineno or node.lineno,
                start_column=_character_column(source_lines[node.lineno - 1], node.col_offset),
                parent_node=parent_node,
                relative_path=relative_path,
            )
        if isinstance(node, ast.ClassDef):
            start_line, start_column = _declaration_origin(node, source_lines, decorator_origins)
            return self._make_class_node(
                node=node,
                parent_node=parent_node,
                relative_path=relative_path,
                start_line=start_line,
                start_column=start_column,
            )
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            start_line, start_column = _declaration_origin(node, source_lines, decorator_origins)
            return self._make_callable_node(
                node=node,
                parent_node=parent_node,
                relative_path=relative_path,
                start_line=start_line,
                start_column=start_column,
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
        start_column: int,
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
        return new_node(
            type_="import",
            path=relative_path,
            start_line=lineno,
            start_column=start_column,
            name=module or None,
            language="py",
            parent_id=parent_node.id,
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
        start_line: int,
        start_column: int,
    ) -> CodeNode:
        return new_node(
            type_="class",
            path=relative_path,
            start_line=start_line,
            start_column=start_column,
            name=node.name,
            language="py",
            parent_id=parent_node.id,
            end_line=node.end_lineno or node.lineno,
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
        start_line: int,
        start_column: int,
    ) -> CodeNode:
        node_type = "method" if parent_node.type == "class" else "function"
        params = self._extract_params(node.args)
        returns = self._expr_to_source(node.returns)
        arguments_source = self._expr_to_source(node.args)
        signature = f"{node.name}({arguments_source if arguments_source is not None else '...'})"
        if returns:
            signature = f"{signature} -> {returns}"
        return new_node(
            type_=node_type,
            path=relative_path,
            start_line=start_line,
            start_column=start_column,
            name=node.name,
            language="py",
            parent_id=parent_node.id,
            end_line=node.end_lineno or node.lineno,
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
        for kwonly_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
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
        except (RecursionError, ValueError) as exc:
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
