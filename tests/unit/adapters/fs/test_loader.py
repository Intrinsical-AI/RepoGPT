from __future__ import annotations

import hashlib
from pathlib import Path

from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.domain.files import CollectedFile


def test_loader_reads_bytes_and_hash_once(tmp_path: Path) -> None:
    content = "# café ☕\nprint('héllo')\n"
    raw = content.encode("utf-8")
    path = tmp_path / "unicode.py"
    path.write_bytes(raw)

    loaded = DefaultLoader().load(
        CollectedFile(abs_path=path, relative_path="unicode.py", language="py")
    )

    assert loaded.raw_bytes == raw
    assert loaded.text == content
    assert loaded.digest.size == len(raw)
    assert loaded.digest.sha256 == hashlib.sha256(raw).hexdigest()
