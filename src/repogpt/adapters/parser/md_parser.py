from __future__ import annotations

import re
from typing import Any

from repogpt.models import CodeNode, ParserInput, ParserInterface
from repogpt.utils.node_utils import stable_node_id
from repogpt.utils.text_processing import count_blank_lines, extract_comments


class MarkdownParser(ParserInterface):
    HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    FENCE_RE = re.compile(r"^```([^\s`]*)\s*$")

    def parse(self, input: ParserInput) -> CodeNode:
        path = input.file_path
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total_lines = max(len(lines), 1)
        relative_path = str(input.file_info.get("relative_path") or path.as_posix())

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
                "heading_count": 0,
                "code_block_count": 0,
                "link_count": 0,
            },
            attributes={"relative_path": relative_path},
        )

        heading_stack: list[CodeNode] = []
        open_code_block: dict[str, Any] | None = None

        for line_number, line in enumerate(lines, start=1):
            heading_match = self.HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                while heading_stack and int(heading_stack[-1].attributes["level"]) >= level:
                    heading_stack.pop()
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
                root.metrics["heading_count"] = int(root.metrics["heading_count"]) + 1
                continue

            fence_match = self.FENCE_RE.match(line)
            if fence_match:
                if open_code_block is None:
                    open_code_block = {
                        "start_line": line_number,
                        "fence_language": fence_match.group(1) or None,
                        "parent": heading_stack[-1] if heading_stack else root,
                    }
                else:
                    parent = open_code_block["parent"]
                    code_block = CodeNode(
                        id=stable_node_id(
                            path=relative_path,
                            type_="code_block",
                            name=open_code_block["fence_language"],
                            start_line=int(open_code_block["start_line"]),
                            end_line=line_number,
                            parent_id=parent.id,
                        ),
                        type="code_block",
                        name=open_code_block["fence_language"],
                        language="md",
                        path=relative_path,
                        start_line=int(open_code_block["start_line"]),
                        end_line=line_number,
                        parent_id=parent.id,
                        attributes={
                            "fence_language": open_code_block["fence_language"],
                        },
                    )
                    parent.children.append(code_block)
                    root.metrics["code_block_count"] = int(root.metrics["code_block_count"]) + 1
                    open_code_block = None

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
                    attributes={"text": link_match.group(1), "url": link_match.group(2)},
                    dependencies=[{"text": link_match.group(1), "url": link_match.group(2)}],
                )
                parent.children.append(link_node)
                root.metrics["link_count"] = int(root.metrics["link_count"]) + 1

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
