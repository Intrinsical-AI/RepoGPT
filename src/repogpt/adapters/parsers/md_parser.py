from __future__ import annotations

import re
from typing import Any

from repogpt.domain.files import LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.parsers import ParserPort
from repogpt.utils.node_utils import stable_node_id
from repogpt.utils.text_processing import count_blank_lines, extract_comments, physical_lines


class _IndentedCodeContext:
    """Track paragraph and list indentation without changing the emitted tree."""

    LIST_ITEM_RE = re.compile(r" {0,3}(?:[-+*]|(?P<number>[0-9]{1,9})[.)])(?P<padding> +|$)")
    THEMATIC_BREAK_RE = re.compile(r" {0,3}(?:(?:\* *){3,}|(?:- *){3,}|(?:_ *){3,})$")

    def __init__(self) -> None:
        self.paragraph_open = False
        self.list_indents: list[int] = []

    def contains(self, line: str, *, starts_block: bool) -> bool:
        # Tabs affect block indentation, but link columns use the original line.
        expanded = line.expandtabs(4)
        if not expanded.strip():
            self.paragraph_open = False
            return False
        starts_block = starts_block or bool(self.THEMATIC_BREAK_RE.fullmatch(expanded))
        indent = len(expanded) - len(expanded.lstrip(" "))
        within_list = bool(self.list_indents)
        if (
            self.list_indents
            and indent < self.list_indents[-1]
            and self.paragraph_open
            and not starts_block
            and not self.LIST_ITEM_RE.match(expanded)
        ):
            # A lazy paragraph continuation does not end its enclosing list.
            return False
        while self.list_indents and indent < self.list_indents[-1]:
            self.list_indents.pop()
        offset = self.list_indents[-1] if self.list_indents else 0
        if indent >= offset + 4:
            return not self.paragraph_open

        remainder = expanded[offset:]
        if self.THEMATIC_BREAK_RE.fullmatch(remainder):
            self.paragraph_open = False
            return False
        item = self.LIST_ITEM_RE.match(remainder)
        if item and self.paragraph_open and not within_list:
            # Only nonempty bullets or an ordered item numbered 1 interrupt prose.
            if item.group("number") not in {None, "1"} or not remainder[item.end() :].strip():
                return False
        while item is not None:
            padding = len(item.group("padding"))
            # More than four spaces: one separates the marker, the rest is code.
            width = item.end() - padding + 1 if padding > 4 else item.end()
            if padding == 0:
                width += 1
            offset += width
            self.list_indents.append(offset)
            remainder = remainder[width:]
            self.paragraph_open = False
            if remainder.startswith("    "):
                return True
            item = self.LIST_ITEM_RE.match(remainder)
        self.paragraph_open = bool(remainder.strip()) and not starts_block
        return False


class MarkdownParser(ParserPort):
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

    def _close_headings(
        self, heading_stack: list[CodeNode], *, min_level: int, end_line: int
    ) -> None:
        while heading_stack and int(heading_stack[-1].attributes["level"]) >= min_level:
            heading_stack[-1].end_line = end_line
            heading_stack.pop()

    def _build_code_block_node(
        self,
        *,
        relative_path: str,
        parent: CodeNode,
        start_line: int,
        end_line: int,
        fence_language: str | None,
        is_unclosed: bool = False,
    ) -> CodeNode:
        attributes: dict[str, Any] = {"fence_language": fence_language}
        if is_unclosed:
            attributes["is_unclosed"] = True
        return CodeNode(
            id=stable_node_id(
                path=relative_path,
                type_="code_block",
                name=fence_language,
                start_line=start_line,
                end_line=end_line,
                parent_id=parent.id,
            ),
            type="code_block",
            name=fence_language,
            language="md",
            path=relative_path,
            start_line=start_line,
            end_line=end_line,
            parent_id=parent.id,
            attributes=attributes,
        )

    def parse(self, loaded_file: LoadedFile) -> CodeNode:
        path = loaded_file.abs_path
        content = loaded_file.text
        lines = physical_lines(content)
        total_lines = max(len(lines), 1)
        relative_path = loaded_file.relative_path

        heading_count = 0
        code_block_count = 0
        link_count = 0
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
            language="md",
            path=relative_path,
            start_line=1,
            end_line=total_lines,
            metrics={
                "blank_lines": count_blank_lines(content),
                "non_empty_lines": len([line for line in lines if line.strip()]),
            },
            attributes={"relative_path": relative_path},
        )

        heading_stack: list[CodeNode] = []
        open_code_block: dict[str, Any] | None = None
        indented_code = _IndentedCodeContext()

        for line_number, line in enumerate(lines, start=1):
            fence_match = self.FENCE_RE.match(line)
            if open_code_block is not None:
                if (
                    fence_match
                    and fence_match.group(1)[0] == open_code_block["delimiter"][0]
                    and len(fence_match.group(1)) >= len(open_code_block["delimiter"])
                    and not fence_match.group(2).strip(" \t")
                ):
                    code_block = self._build_code_block_node(
                        relative_path=relative_path,
                        parent=open_code_block["parent"],
                        start_line=int(open_code_block["start_line"]),
                        end_line=line_number,
                        fence_language=open_code_block["fence_language"],
                    )
                    open_code_block["parent"].children.append(code_block)
                    code_block_count += 1
                    open_code_block = None
                continue

            heading_match = self.HEADING_RE.match(line)
            if fence_match and fence_match.group(1)[0] == "`" and "`" in fence_match.group(2):
                fence_match = None
            if indented_code.contains(line, starts_block=bool(fence_match or heading_match)):
                continue

            if fence_match:
                delimiter, info = fence_match.groups()
                language = info.strip().split()
                open_code_block = {
                    "start_line": line_number,
                    "fence_language": language[0] if language else None,
                    "delimiter": delimiter,
                    "parent": heading_stack[-1] if heading_stack else root,
                }
                continue

            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                self._close_headings(
                    heading_stack,
                    min_level=level,
                    end_line=line_number - 1,
                )
                parent = heading_stack[-1] if heading_stack else root
                node = CodeNode(
                    id=stable_node_id(
                        path=relative_path,
                        type_="heading",
                        name=title,
                        start_line=line_number,
                        end_line=line_number,
                        parent_id=parent.id,
                    ),
                    type="heading",
                    name=title,
                    language="md",
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    parent_id=parent.id,
                    attributes={"level": level},
                )
                parent.children.append(node)
                heading_stack.append(node)
                heading_count += 1
                continue

            for link_match in self.LINK_RE.finditer(line):
                parent = heading_stack[-1] if heading_stack else root
                link_node = CodeNode(
                    id=stable_node_id(
                        path=relative_path,
                        type_="link",
                        name=link_match.group(1),
                        start_line=line_number,
                        end_line=line_number,
                        parent_id=parent.id,
                        start_column=link_match.start(),
                    ),
                    type="link",
                    name=link_match.group(1),
                    language="md",
                    path=relative_path,
                    start_line=line_number,
                    end_line=line_number,
                    parent_id=parent.id,
                    attributes={
                        "text": link_match.group(1),
                        "url": link_match.group(2),
                        "start_column": link_match.start(),
                    },
                    dependencies=[{"text": link_match.group(1), "url": link_match.group(2)}],
                )
                parent.children.append(link_node)
                link_count += 1

        if open_code_block is not None:
            code_block = self._build_code_block_node(
                relative_path=relative_path,
                parent=open_code_block["parent"],
                start_line=int(open_code_block["start_line"]),
                end_line=total_lines,
                fence_language=open_code_block["fence_language"],
                is_unclosed=True,
            )
            open_code_block["parent"].children.append(code_block)
            code_block_count += 1

        self._close_headings(heading_stack, min_level=1, end_line=total_lines)
        root.metrics["heading_count"] = heading_count
        root.metrics["code_block_count"] = code_block_count
        root.metrics["link_count"] = link_count

        comments = extract_comments(content, language="markdown")
        root.comments.extend(comments)
        dedup_tags: list[str] = []
        for comment in comments:
            lowered = str(comment["text"]).lower()
            if "todo" in lowered and "TODO" not in dedup_tags:
                dedup_tags.append("TODO")
            if "fixme" in lowered and "FIXME" not in dedup_tags:
                dedup_tags.append("FIXME")
        root.tags = dedup_tags
        return root
