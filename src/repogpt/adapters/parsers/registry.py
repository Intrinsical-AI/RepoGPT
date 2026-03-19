from __future__ import annotations

from repogpt.adapters.parsers.md_parser import MarkdownParser
from repogpt.adapters.parsers.py_parser import PythonParser
from repogpt.ports.parsers import ParserPort, ParserRegistryPort


class StaticParserRegistry(ParserRegistryPort):
    def __init__(self) -> None:
        self._parsers: dict[str, ParserPort] = {
            "py": PythonParser(),
            "md": MarkdownParser(),
        }

    def supported_extensions(self) -> set[str]:
        return set(self._parsers)

    def parser_for(self, extension: str) -> ParserPort | None:
        return self._parsers.get(extension)
