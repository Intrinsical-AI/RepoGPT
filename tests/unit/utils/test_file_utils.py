import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock structlog before importing the module that uses it
import sys
sys.modules["structlog"] = MagicMock()

from repogpt.utils.file_utils import calculate_file_hash, is_likely_binary, CHUNK_SIZE

def test_calculate_file_hash_success(tmp_path: Path) -> None:
    file = tmp_path / "test.txt"
    content = b"hello world"
    file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert calculate_file_hash(file) == expected_hash

def test_calculate_file_hash_large_file(tmp_path: Path) -> None:
    file = tmp_path / "large_test.txt"
    # Create a file larger than CHUNK_SIZE (8192)
    content = b"a" * (CHUNK_SIZE + 100)
    file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    assert calculate_file_hash(file) == expected_hash

def test_calculate_file_hash_different_algorithm(tmp_path: Path) -> None:
    file = tmp_path / "test_md5.txt"
    content = b"hello world"
    file.write_bytes(content)

    expected_hash = hashlib.md5(content).hexdigest()
    assert calculate_file_hash(file, algorithm="md5") == expected_hash

def test_calculate_file_hash_file_not_found() -> None:
    assert calculate_file_hash(Path("non_existent_file.txt")) is None

def test_calculate_file_hash_invalid_algorithm(tmp_path: Path) -> None:
    file = tmp_path / "test.txt"
    file.write_bytes(b"content")
    assert calculate_file_hash(file, algorithm="invalid_algo") is None

def test_calculate_file_hash_permission_error(tmp_path: Path) -> None:
    file = tmp_path / "perm_error.txt"
    file.write_bytes(b"content")

    with patch.object(Path, "open", side_effect=PermissionError):
        assert calculate_file_hash(file) is None

def test_calculate_file_hash_os_error(tmp_path: Path) -> None:
    file = tmp_path / "os_error.txt"
    file.write_bytes(b"content")

    with patch.object(Path, "open", side_effect=OSError("Disk failure")):
        assert calculate_file_hash(file) is None

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

def test_is_likely_binary_file_not_found() -> None:
    assert is_likely_binary(Path("non_existent_file.bin")) is False

def test_is_likely_binary_permission_error(tmp_path: Path) -> None:
    file = tmp_path / "perm_error.bin"
    file.touch()

    with patch.object(Path, "open", side_effect=PermissionError):
        assert is_likely_binary(file) is False

def test_is_likely_binary_os_error(tmp_path: Path) -> None:
    file = tmp_path / "os_error.bin"
    file.touch()

    with patch.object(Path, "open", side_effect=OSError("Disk failure")):
        assert is_likely_binary(file) is False

def test_is_likely_binary_unexpected_exception(tmp_path: Path) -> None:
    file = tmp_path / "unexpected.bin"
    file.touch()

    with patch.object(Path, "open", side_effect=Exception("Unexpected")):
        assert is_likely_binary(file) is False
