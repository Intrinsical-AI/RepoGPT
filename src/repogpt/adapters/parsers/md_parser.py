from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from repogpt.domain.files import LoadedFile
from repogpt.domain.nodes import CodeNode
from repogpt.ports.parsers import ParserPort
from repogpt.utils.node_utils import new_node
from repogpt.utils.text_processing import count_blank_lines, extract_comments, physical_lines


class _IndentedCodeContext:
    """Track paragraph and list indentation without changing the emitted tree."""

    LIST_ITEM_RE = re.compile(r" {0,3}(?:[-+*]|(?P<number>[0-9]{1,9})[.)])(?P<padding> +|$)")
    THEMATIC_BREAK_RE = re.compile(r" {0,3}(?:(?:\* *){3,}|(?:- *){3,}|(?:_ *){3,})$")

    def __init__(self) -> None:
        self.paragraph_open = False
        self.list_indents: list[int] = []
        self.list_item_started = False
        self.block_line = ""
        self.block_offset = 0

    def contains(self, line: str, *, starts_block: bool) -> bool:
        # Tabs affect block indentation, but link columns use the original line.
        expanded = line.expandtabs(4)
        self.list_item_started = False
        self.block_line = expanded
        self.block_offset = 0
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
        self.block_line = expanded[offset:]
        self.block_offset = offset
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
            self.list_item_started = True
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
            if self.THEMATIC_BREAK_RE.fullmatch(remainder):
                self.block_line = remainder
                self.block_offset = offset
                return False
            item = self.LIST_ITEM_RE.match(remainder)
        self.block_line = remainder
        self.block_offset = offset
        self.paragraph_open = bool(remainder.strip()) and not starts_block
        return False


@dataclass
class _OpenFence:
    start_line: int
    start_column: int
    fence_language: str | None
    delimiter: str
    parent: CodeNode
    container_indent: int


class MarkdownParser(ParserPort):
    HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
    HEADING_START_RE = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
    LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

    @classmethod
    def _match_fence(cls, line: str) -> re.Match[str] | None:
        match = cls.FENCE_RE.match(line)
        if match and match.group(1)[0] == "`" and "`" in match.group(2):
            return None
        return match

    @staticmethod
    def _original_column(line: str, expanded_column: int) -> int:
        """Translate an expanded-tab column back to a character offset in the source."""
        column = 0
        for index, character in enumerate(line):
            if column == expanded_column:
                return index
            column += 4 - column % 4 if character == "\t" else 1
            if column > expanded_column:
                raise ValueError("Markdown marker begins inside an expanded tab")
        if column == expanded_column:
            return len(line)
        raise ValueError("Markdown marker column exceeds the physical line")

    @staticmethod
    def _blank_inline_code(text: str) -> str:
        """Blank complete code spans within one inline block, preserving newlines."""
        masked = list(text)
        position = 0
        while position < len(text):
            if text[position] == "\\":
                position += 2
                continue
            if text[position] != "`":
                position += 1
                continue
            run_end = position + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            run_length = run_end - position
            search = run_end
            closing_end: int | None = None
            while search < len(text):
                candidate = text.find("`", search)
                if candidate < 0:
                    break
                candidate_end = candidate + 1
                while candidate_end < len(text) and text[candidate_end] == "`":
                    candidate_end += 1
                if candidate_end - candidate == run_length:
                    closing_end = candidate_end
                    break
                search = candidate_end
            if closing_end is None:
                position = run_end
            else:
                masked[position:closing_end] = [
                    character if character in "\r\n" else " "
                    for character in text[position:closing_end]
                ]
                position = closing_end
        return "".join(masked)

    @staticmethod
    def _is_image(line: str, link_start: int) -> bool:
        if link_start == 0 or line[link_start - 1] != "!":
            return False
        backslashes = 0
        position = link_start - 2
        while position >= 0 and line[position] == "\\":
            backslashes += 1
            position -= 1
        return backslashes % 2 == 0

    @classmethod
    def _mask_code_lines(
        cls, content: str, excluded_lines: set[int], inline_lines: dict[int, str]
    ) -> str:
        masked: list[str] = []
        for line_number, line in enumerate(physical_lines(content, keepends=True), start=1):
            body = line.rstrip("\r\n")
            newline = line[len(body) :]
            if line_number in excluded_lines:
                masked_body = " " * len(body)
            elif line_number in inline_lines:
                masked_body = inline_lines[line_number]
            else:
                masked_body = cls._blank_inline_code(body)
            masked.append(masked_body + newline)
        return "".join(masked)

    def _flush_inline_lines(
        self,
        pending: list[tuple[int, str, CodeNode]],
        *,
        relative_path: str,
        inline_lines: dict[int, str],
    ) -> int:
        if not pending:
            return 0
        masked_lines = self._blank_inline_code("\n".join(line for _, line, _ in pending)).split(
            "\n"
        )
        link_count = 0
        for (line_number, line, parent), masked_line in zip(pending, masked_lines, strict=True):
            inline_lines[line_number] = masked_line
            for link_match in self.LINK_RE.finditer(masked_line):
                if self._is_image(line, link_match.start()):
                    continue
                link_node = new_node(
                    type_="link",
                    path=relative_path,
                    start_line=line_number,
                    start_column=link_match.start(),
                    name=link_match.group(1),
                    language="md",
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
        pending.clear()
        return link_count

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
        start_column: int,
        end_line: int,
        fence_language: str | None,
        is_unclosed: bool = False,
    ) -> CodeNode:
        attributes: dict[str, Any] = {"fence_language": fence_language}
        if is_unclosed:
            attributes["is_unclosed"] = True
        return new_node(
            type_="code_block",
            path=relative_path,
            start_line=start_line,
            start_column=start_column,
            name=fence_language,
            language="md",
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
        root = new_node(
            type_="module",
            path=relative_path,
            start_line=1,
            start_column=0,
            name=path.stem,
            language="md",
            end_line=total_lines,
            metrics={
                "blank_lines": count_blank_lines(content),
                "non_empty_lines": len([line for line in lines if line.strip()]),
            },
            attributes={"relative_path": relative_path},
        )

        heading_stack: list[CodeNode] = []
        open_code_block: _OpenFence | None = None
        indented_code = _IndentedCodeContext()
        code_lines: set[int] = set()
        inline_lines: dict[int, str] = {}
        pending_inline: list[tuple[int, str, CodeNode]] = []

        def flush_inline() -> None:
            nonlocal link_count
            link_count += self._flush_inline_lines(
                pending_inline, relative_path=relative_path, inline_lines=inline_lines
            )

        for line_number, line in enumerate(lines, start=1):
            fence_match = self._match_fence(line)
            if open_code_block is not None:
                expanded = line.expandtabs(4)
                container_indent = open_code_block.container_indent
                in_container = not expanded.strip() or (
                    len(expanded) - len(expanded.lstrip(" ")) >= container_indent
                )
                fence_match = self._match_fence(expanded[container_indent:])
                closing = bool(
                    fence_match
                    and fence_match.group(1)[0] == open_code_block.delimiter[0]
                    and len(fence_match.group(1)) >= len(open_code_block.delimiter)
                    and not fence_match.group(2).strip(" \t")
                )
                if closing or not in_container:
                    end_line = line_number if in_container else line_number - 1
                    code_block = self._build_code_block_node(
                        relative_path=relative_path,
                        parent=open_code_block.parent,
                        start_line=open_code_block.start_line,
                        start_column=open_code_block.start_column,
                        end_line=end_line,
                        fence_language=open_code_block.fence_language,
                        is_unclosed=not in_container,
                    )
                    open_code_block.parent.children.append(code_block)
                    code_block_count += 1
                    code_lines.update(range(open_code_block.start_line, end_line + 1))
                    open_code_block = None
                if in_container:
                    continue
                fence_match = self._match_fence(line)

            starts_heading = bool(self.HEADING_START_RE.match(line))
            if indented_code.contains(line, starts_block=bool(fence_match or starts_heading)):
                flush_inline()
                code_lines.add(line_number)
                continue

            # Lists contribute container indentation, not paragraph text. Retain
            # original source lines/columns while recognizing their block starts.
            block_line = indented_code.block_line
            fence_match = self._match_fence(block_line)
            heading_match = self.HEADING_RE.match(block_line)
            if fence_match or heading_match:
                indented_code.paragraph_open = False

            if not line.strip() or indented_code.THEMATIC_BREAK_RE.fullmatch(block_line):
                flush_inline()
                continue

            if fence_match:
                flush_inline()
                delimiter, info = fence_match.groups()
                language = info.strip().split()
                open_code_block = _OpenFence(
                    start_line=line_number,
                    start_column=self._original_column(
                        line, indented_code.block_offset + fence_match.start(1)
                    ),
                    fence_language=language[0] if language else None,
                    delimiter=delimiter,
                    parent=heading_stack[-1] if heading_stack else root,
                    container_indent=(
                        indented_code.list_indents[-1] if indented_code.list_indents else 0
                    ),
                )
                continue

            if heading_match:
                flush_inline()
                level = len(heading_match.group(1))
                title = (heading_match.group(2) or "").strip()
                self._close_headings(
                    heading_stack,
                    min_level=level,
                    end_line=line_number - 1,
                )
                parent = heading_stack[-1] if heading_stack else root
                node = new_node(
                    type_="heading",
                    path=relative_path,
                    start_line=line_number,
                    start_column=self._original_column(
                        line, indented_code.block_offset + heading_match.start(1)
                    ),
                    name=title,
                    language="md",
                    end_line=line_number,
                    parent_id=parent.id,
                    attributes={"level": level},
                )
                parent.children.append(node)
                heading_stack.append(node)
                heading_count += 1
                continue

            if indented_code.list_item_started:
                flush_inline()
            pending_inline.append((line_number, line, heading_stack[-1] if heading_stack else root))

        flush_inline()
        if open_code_block is not None:
            code_block = self._build_code_block_node(
                relative_path=relative_path,
                parent=open_code_block.parent,
                start_line=open_code_block.start_line,
                start_column=open_code_block.start_column,
                end_line=total_lines,
                fence_language=open_code_block.fence_language,
                is_unclosed=True,
            )
            open_code_block.parent.children.append(code_block)
            code_block_count += 1
            code_lines.update(range(open_code_block.start_line, total_lines + 1))

        self._close_headings(heading_stack, min_level=1, end_line=total_lines)
        root.metrics["heading_count"] = heading_count
        root.metrics["code_block_count"] = code_block_count
        root.metrics["link_count"] = link_count

        comments = extract_comments(
            self._mask_code_lines(content, code_lines, inline_lines), language="markdown"
        )
        root.comments.extend(comments)
        dedup_tags: list[str] = []
        for comment in comments:
            for match in re.finditer(r"\b(TODO|FIXME)\b", str(comment["text"]), re.IGNORECASE):
                tag = match.group(1).upper()
                if tag not in dedup_tags:
                    dedup_tags.append(tag)
        root.tags = dedup_tags
        return root
