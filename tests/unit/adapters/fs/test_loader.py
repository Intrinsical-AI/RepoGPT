from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.domain.files import CollectedFile


def test_collected_file_rejects_an_empty_relative_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relative_path must not be empty"):
        CollectedFile(abs_path=tmp_path / "sample.py", relative_path="", extension="py")


def test_loader_decodes_text_and_hashes_original_bytes(tmp_path: Path) -> None:
    content = "# café ☕\nprint('héllo')\n"
    raw = content.encode("utf-8")
    path = tmp_path / "unicode.py"
    path.write_bytes(raw)

    loaded = DefaultLoader().load(
        CollectedFile(abs_path=path, relative_path="unicode.py", extension="py")
    )

    assert loaded.text == content
    assert loaded.digest.size == len(raw)
    assert loaded.digest.sha256 == hashlib.sha256(raw).hexdigest()


def test_loader_rejects_invalid_markdown_utf8_without_replacement(tmp_path: Path) -> None:
    path = tmp_path / "invalid.md"
    path.write_bytes(b"# bad\xff\n")
    loaded = DefaultLoader().load(
        CollectedFile(abs_path=path, relative_path="invalid.md", extension="md")
    )
    assert loaded.decode_error is not None
    assert loaded.text == ""


def test_loader_strips_markdown_utf8_bom_without_changing_digest(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf# Title\n"
    path = tmp_path / "bom.md"
    path.write_bytes(raw)

    loaded = DefaultLoader().load(
        CollectedFile(abs_path=path, relative_path="bom.md", extension="md")
    )

    assert loaded.text == "# Title\n"
    assert loaded.digest.size == len(raw)
    assert loaded.digest.sha256 == hashlib.sha256(raw).hexdigest()
