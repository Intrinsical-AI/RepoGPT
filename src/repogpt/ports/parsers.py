from __future__ import annotations

from typing import Protocol

from repogpt.domain.files import LoadedFile
from repogpt.domain.nodes import CodeNode


class ParserPort(Protocol):
    def parse(self, loaded_file: LoadedFile) -> CodeNode: ...


class ParserRegistryPort(Protocol):
    def supported_extensions(self) -> set[str]: ...

    def parser_for(self, extension: str) -> ParserPort | None: ...
