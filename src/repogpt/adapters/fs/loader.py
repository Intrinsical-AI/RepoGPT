from __future__ import annotations

import hashlib
import io
import re
import tokenize

from repogpt.domain.errors import CollectionFailure
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.ports.loader import LoaderPort


class DefaultLoader(LoaderPort):
    def load(self, collected_file: CollectedFile) -> LoadedFile:
        try:
            raw_bytes = collected_file.abs_path.read_bytes()
        except OSError as exc:
            raise CollectionFailure(f"Cannot read {collected_file.relative_path}: {exc}") from exc
        decode_error = None
        try:
            if collected_file.language == "py":
                # Encoding detection uses Python physical lines, including CR-only files.
                detection_bytes = re.sub(rb"\r\n?", b"\n", raw_bytes)
                encoding, _ = tokenize.detect_encoding(io.BytesIO(detection_bytes).readline)
                text = raw_bytes.decode(encoding)
            else:
                text = raw_bytes.decode("utf-8", errors="replace")
        except (UnicodeError, SyntaxError, LookupError) as exc:
            text = ""
            decode_error = f"{type(exc).__name__}: {exc}"
        return LoadedFile(
            collected_file=collected_file,
            text=text,
            decode_error=decode_error,
            digest=FileDigest(
                size=len(raw_bytes),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
            ),
        )
