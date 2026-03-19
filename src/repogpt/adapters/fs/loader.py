from __future__ import annotations

import hashlib

from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.ports.loader import LoaderPort


class DefaultLoader(LoaderPort):
    def load(self, collected_file: CollectedFile) -> LoadedFile:
        raw_bytes = collected_file.abs_path.read_bytes()
        return LoadedFile(
            collected_file=collected_file,
            raw_bytes=raw_bytes,
            text=raw_bytes.decode("utf-8", errors="replace"),
            digest=FileDigest(
                size=len(raw_bytes),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
            ),
        )
