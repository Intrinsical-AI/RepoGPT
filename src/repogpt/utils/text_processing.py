import bisect
import io
import re
import tokenize
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def physical_lines(text: str, *, keepends: bool = False) -> list[str]:
    """Split only LF, CRLF and CR, preserving all other source characters."""
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n|$)", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines if keepends else [line.rstrip("\r\n") for line in lines]


def count_blank_lines(text: str) -> int:
    """Count fully blank lines."""
    return sum(1 for line in physical_lines(text) if not line.strip())


def extract_comments(content: str, language: str = "python") -> list[dict[str, Any]]:
    """Extract comments with their starting line number."""
    comments = []
    if language == "python":
        try:
            normalized = re.sub(r"\r\n?", "\n", content)
            tokens = tokenize.generate_tokens(io.StringIO(normalized).readline)
            for toktype, tok, start, _, _ in tokens:
                if toktype == tokenize.COMMENT:
                    comments.append(
                        {
                            "text": tok[1:].lstrip(" ").rstrip(),
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
        newline_offsets = [match.end() - 1 for match in re.finditer(r"\r\n|\r|\n", content)]
        for match in re.finditer(r"<!--(.*?)-->", content, re.DOTALL):
            line = bisect.bisect_left(newline_offsets, match.start()) + 1
            comments.append(
                {
                    "text": match.group(1).strip(),
                    "line": line,
                }
            )
    return comments
