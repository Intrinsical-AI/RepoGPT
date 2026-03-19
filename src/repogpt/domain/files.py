from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repogpt.domain.errors import ParseFailure
from repogpt.domain.nodes import CodeNode


@dataclass(frozen=True)
class FileDigest:
    size: int
    sha256: str


@dataclass(frozen=True)
class CollectedFile:
    abs_path: Path
    relative_path: str
    language: str


@dataclass(frozen=True)
class SkippedFile:
    abs_path: Path
    relative_path: str
    reason: str


@dataclass(frozen=True)
class LoadedFile:
    collected_file: CollectedFile
    raw_bytes: bytes
    text: str
    digest: FileDigest

    @property
    def abs_path(self) -> Path:
        return self.collected_file.abs_path

    @property
    def relative_path(self) -> str:
        return self.collected_file.relative_path

    @property
    def language(self) -> str:
        return self.collected_file.language


@dataclass(frozen=True)
class ParsedFile:
    loaded_file: LoadedFile
    root: CodeNode | None
    failure: ParseFailure | None = None

    def __post_init__(self) -> None:
        if self.root is None and self.failure is None:
            raise ValueError("ParsedFile requires failure when root is None")
        if self.root is not None and self.failure is not None:
            raise ValueError("ParsedFile cannot contain both root and failure")

    @property
    def abs_path(self) -> Path:
        return self.loaded_file.abs_path

    @property
    def relative_path(self) -> str:
        return self.loaded_file.relative_path

    @property
    def language(self) -> str:
        return self.loaded_file.language

    @property
    def digest(self) -> FileDigest:
        return self.loaded_file.digest

    @property
    def text(self) -> str:
        return self.loaded_file.text
