from pathlib import Path
from unittest.mock import patch

import pytest

from repogpt.utils.file_utils import is_likely_binary


def test_is_likely_binary_text_file(tmp_path: Path) -> None:
    file = tmp_path / "text.txt"
    file.write_text("This is a normal text file.")
    assert is_likely_binary(file) is False


def test_is_likely_binary_binary_file(tmp_path: Path) -> None:
    file = tmp_path / "binary.bin"
    file.write_bytes(b"Some data\x00More data")
    assert is_likely_binary(file) is True


def test_is_likely_binary_empty_file(tmp_path: Path) -> None:
    file = tmp_path / "empty.txt"
    file.touch()
    assert is_likely_binary(file) is False


@pytest.mark.parametrize(
    "error", [FileNotFoundError("gone"), PermissionError("denied"), OSError("disk")]
)
def test_binary_probe_propagates_read_errors(tmp_path: Path, error: OSError) -> None:
    with patch.object(Path, "open", side_effect=error), pytest.raises(type(error)):
        is_likely_binary(tmp_path / "file.py")
