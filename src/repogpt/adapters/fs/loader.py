from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import tokenize

from repogpt.domain.errors import CollectionFailure, FileAdmissionSkipped
from repogpt.domain.files import CollectedFile, FileDigest, LoadedFile
from repogpt.ports.loader import LoaderPort


class DefaultLoader(LoaderPort):
    def load(self, collected_file: CollectedFile) -> LoadedFile:
        try:
            admitted = collected_file.abs_path.lstat()
            if not stat.S_ISREG(admitted.st_mode):
                raise FileAdmissionSkipped("non_regular_file")
            if admitted.st_size > collected_file.max_file_size:
                raise FileAdmissionSkipped("file_too_large")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(collected_file.abs_path, flags), "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise FileAdmissionSkipped("non_regular_file")
                if (admitted.st_dev, admitted.st_ino) != (before.st_dev, before.st_ino):
                    raise CollectionFailure(
                        f"Source replaced before reading {collected_file.relative_path}"
                    )
                if before.st_size > collected_file.max_file_size:
                    raise FileAdmissionSkipped("file_too_large")
                raw_bytes = stream.read(collected_file.max_file_size + 1)
                after = os.fstat(stream.fileno())
            if len(raw_bytes) > collected_file.max_file_size:
                raise FileAdmissionSkipped("file_too_large")
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise CollectionFailure(
                    f"Source changed while reading {collected_file.relative_path}"
                )
            if b"\x00" in raw_bytes[:1024]:
                raise FileAdmissionSkipped("binary_file")
        except OSError as exc:
            raise CollectionFailure(f"Cannot read {collected_file.relative_path}: {exc}") from exc
        decode_error = None
        try:
            if collected_file.extension == "py":
                # Encoding detection uses Python physical lines, including CR-only files.
                detection_bytes = re.sub(rb"\r\n?", b"\n", raw_bytes)
                encoding, _ = tokenize.detect_encoding(io.BytesIO(detection_bytes).readline)
                text = raw_bytes.decode(encoding)
            else:
                text = raw_bytes.decode("utf-8-sig")
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
