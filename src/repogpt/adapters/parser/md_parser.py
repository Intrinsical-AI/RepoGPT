from __future__ import annotations

import re
from typing import Any

from repogpt.models import CodeNode, ParserInput, ParserInterface
from repogpt.utils.node_utils import stable_node_id
from repogpt.utils.text_processing import count_blank_lines, extract_comments


class MarkdownParser(ParserInterface):
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    FENCE_RE = re.compile(r"^(```|~~~)(\S*)(?: .*)?$")

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

    def parse(self, parser_input: ParserInput) -> CodeNode:
        path = parser_input.file_path
        content = parser_input.content
        if content is None:
            content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total_lines = max(len(lines), 1)
        relative_path = str(parser_input.file_info.get("relative_path") or path.as_posix())

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

        for line_number, line in enumerate(lines, start=1):
            fence_match = self.FENCE_RE.match(line)
            if fence_match:
                if open_code_block is None:
                    open_code_block = {
                        "start_line": line_number,
                        "fence_language": fence_match.group(2) or None,
                        "delimiter": fence_match.group(1),
                        "parent": heading_stack[-1] if heading_stack else root,
                    }
                elif fence_match.group(1) == open_code_block["delimiter"]:
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

            if open_code_block is not None:
                continue

            heading_match = self.HEADING_RE.match(line)
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
