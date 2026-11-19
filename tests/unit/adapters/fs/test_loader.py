from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from repogpt.adapters.fs.loader import DefaultLoader
from repogpt.domain.errors import CollectionFailure, FileAdmissionSkipped
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


@pytest.mark.parametrize("raw", [b"", b"value = 1\n", b"# text\x00binary"])
def test_loader_reads_original_source_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    path = tmp_path / "sample.py"
    path.write_bytes(raw)
    source_opens: list[Path] = []
    real_open = os.open

    def record_open(value: Path, flags: int) -> int:
        source_opens.append(value)
        return real_open(value, flags)

    monkeypatch.setattr(os, "open", record_open)
    collected = CollectedFile(abs_path=path, relative_path="sample.py", extension="py")
    if b"\x00" in raw:
        with pytest.raises(FileAdmissionSkipped, match="binary_file"):
            DefaultLoader().load(collected)
    else:
        loaded = DefaultLoader().load(collected)
        assert loaded.digest.sha256 == hashlib.sha256(raw).hexdigest()
    assert source_opens == [path]


def test_loader_rejects_a_source_that_grew_after_collection(tmp_path: Path) -> None:
    path = tmp_path / "large.py"
    path.write_bytes(b"1234")
    collected = CollectedFile(
        abs_path=path, relative_path="large.py", extension="py", max_file_size=3
    )
    with pytest.raises(FileAdmissionSkipped, match="file_too_large"):
        DefaultLoader().load(collected)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO requires POSIX")
def test_loader_rejects_fifo_without_opening_or_blocking(tmp_path: Path) -> None:
    path = tmp_path / "pipe.py"
    os.mkfifo(path)
    with pytest.raises(FileAdmissionSkipped, match="non_regular_file"):
        DefaultLoader().load(CollectedFile(abs_path=path, relative_path="pipe.py", extension="py"))


def test_loader_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("value = 1\n")
    path = tmp_path / "link.py"
    path.symlink_to(target)
    with pytest.raises(FileAdmissionSkipped, match="non_regular_file"):
        DefaultLoader().load(CollectedFile(abs_path=path, relative_path="link.py", extension="py"))


def test_loader_rejects_mutation_during_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "changing.py"
    path.write_text("value = 1\n")
    real_fstat = os.fstat
    calls = 0

    def mutate_after_snapshot(fd: int) -> os.stat_result:
        nonlocal calls
        snapshot = real_fstat(fd)
        calls += 1
        if calls == 1:
            path.write_text("value = 123456\n")
        return snapshot

    monkeypatch.setattr(os, "fstat", mutate_after_snapshot)
    with pytest.raises(CollectionFailure, match="Source changed while reading"):
        DefaultLoader().load(
            CollectedFile(abs_path=path, relative_path="changing.py", extension="py")
        )
