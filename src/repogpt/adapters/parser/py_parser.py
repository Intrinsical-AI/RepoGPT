from __future__ import annotations

import ast
from collections.abc import Sequence
from typing import Any

from repogpt.models import CodeNode, ParserInput, ParserInterface
from repogpt.utils.node_utils import stable_node_id
from repogpt.utils.text_processing import count_blank_lines, extract_comments


class PythonParser(ParserInterface):
    def parse(self, input: ParserInput) -> CodeNode:
        path = input.file_path
        content = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(path))
        relative_path = str(input.file_info.get("relative_path") or path.as_posix())

        root = CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="module",
                name=path.stem,
                start_line=1,
                end_line=content.count("\n") + 1,
                parent_id=None,
            ),
            type="module",
            name=path.stem,
            language="py",
            path=relative_path,
            start_line=1,
            end_line=content.count("\n") + 1,
            docstring=ast.get_docstring(tree),
            metrics={
                "blank_lines": count_blank_lines(content),
                "non_empty_lines": len([line for line in content.splitlines() if line.strip()]),
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
                nested_nodes = getattr(child, "body", None)
                if isinstance(nested_nodes, list):
                    self._visit_sequence(
                        nested_nodes,
                        parent_node=parent_node,
                        relative_path=relative_path,
                    )
                continue
            parent_node.children.append(code_node)
            nested_nodes = getattr(child, "body", None)
            if isinstance(nested_nodes, list):
                self._visit_sequence(
                    nested_nodes,
                    parent_node=code_node,
                    relative_path=relative_path,
                )

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
                is_relative=False,
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                parent_node=parent_node,
                relative_path=relative_path,
            )
        if isinstance(node, ast.ImportFrom):
            return self._make_import_node(
                module=node.module,
                aliases=node.names,
                import_kind="from",
                is_relative=bool(node.level),
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
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
        is_relative: bool,
        lineno: int,
        end_lineno: int,
        parent_node: CodeNode,
        relative_path: str,
    ) -> CodeNode:
        attributes = {
            "module": module,
            "import_kind": import_kind,
            "is_relative": is_relative,
            "imported_names": [
                {"name": alias.name, "asname": alias.asname} for alias in aliases
            ],
        }
        imported_names: list[dict[str, Any]] = [
            {"name": alias.name, "asname": alias.asname} for alias in aliases
        ]
        attributes["imported_names"] = imported_names
        return CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="import",
                name=module or ",".join(alias.name for alias in aliases),
                start_line=lineno,
                end_line=end_lineno,
                parent_id=parent_node.id,
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
        signature = self._build_signature(node)
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
                "params": self._extract_params(node.args),
                "returns": self._expr_to_source(node.returns),
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
            if index >= defaults_offset and args.defaults:
                default = self._expr_to_source(args.defaults[index - defaults_offset])
            params.append(
                {
                    "name": arg.arg,
                    "kind": "positional_only" if index < len(args.posonlyargs) else "positional",
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

    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        params = []
        saw_posonly = False
        for param in self._extract_params(node.args):
            if param["kind"] == "positional_only":
                saw_posonly = True
            elif saw_posonly:
                params.append("/")
                saw_posonly = False
            rendered = param["name"]
            annotation = param["annotation"]
            default = param["default"]
            if param["kind"] == "vararg":
                rendered = f"*{rendered}"
            elif param["kind"] == "kwarg":
                rendered = f"**{rendered}"
            elif param["kind"] == "keyword_only" and "*" not in params:
                params.append("*")
            if annotation:
                rendered = f"{rendered}: {annotation}"
            if default is not None:
                rendered = f"{rendered} = {default}"
            params.append(rendered)
        if saw_posonly:
            params.append("/")
        signature = f"{node.name}({', '.join(params)})"
        returns = self._expr_to_source(node.returns)
        if returns:
            signature = f"{signature} -> {returns}"
        return signature

    def _expr_to_source(self, expr: ast.AST | None) -> str | None:
        if expr is None:
            return None
        try:
            return ast.unparse(expr)
        except Exception:
            return None

    def _visibility(self, name: str) -> str:
        if name.startswith("__") and not name.endswith("__"):
            return "private"
        if name.startswith("_"):
            return "protected"
        return "public"

    def _associate_comments(self, root: CodeNode, comments: list[dict[str, Any]]) -> None:
        def walk(node: CodeNode, comment: dict[str, Any]) -> CodeNode | None:
            if (
                node.start_line is not None
                and node.end_line is not None
                and node.start_line <= comment["line"] <= node.end_line
            ):
                for child in node.children:
                    found = walk(child, comment)
                    if found is not None:
                        return found
                return node
            return None

        for comment in comments:
            owner = walk(root, comment) or root
            owner.comments.append(comment)
