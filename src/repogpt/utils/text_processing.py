import bisect
import io
import re
import tokenize
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def count_blank_lines(text: str) -> int:
    """Count fully blank lines."""
    return sum(1 for line in text.splitlines() if not line.strip())


def extract_comments(content: str, language: str = "python") -> list[dict[str, Any]]:
    """Extract comments with their starting line number."""
    comments = []
    if language == "python":
        try:
            tokens = tokenize.generate_tokens(io.StringIO(content).readline)
            for toktype, tok, start, _, _ in tokens:
                if toktype == tokenize.COMMENT:
                    comments.append(
                        {
                            "text": tok.lstrip("# ").rstrip(),
                            "line": start[0],
                        }
                    )
        except Exception as exc:
            logger.debug(
                "python comment extraction failed",
                error=str(exc),
            )
    elif language == "markdown":
        # Pre-compute newline offsets once to avoid O(N*M) line counting.
        newline_offsets = [i for i, ch in enumerate(content) if ch == "\n"]
        for match in re.finditer(r"<!--(.*?)-->", content, re.DOTALL):
            line = bisect.bisect_left(newline_offsets, match.start()) + 1
            comments.append(
                {
                    "text": match.group(1).strip(),
                    "line": line,
                }
            )
    return comments


def extract_todos_fixmes(comments: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Extract TODO and FIXME comment texts."""
    todos: list[str] = []
    fixmes: list[str] = []
    for c in comments:
        lower = c["text"].lower()
        if "todo" in lower:
            todos.append(c["text"])
        if "fixme" in lower:
            fixmes.append(c["text"])
    return todos, fixmes
