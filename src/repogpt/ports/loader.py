from __future__ import annotations

from typing import Protocol

from repogpt.domain.files import CollectedFile, LoadedFile


class LoaderPort(Protocol):
    def load(self, collected_file: CollectedFile) -> LoadedFile: ...
