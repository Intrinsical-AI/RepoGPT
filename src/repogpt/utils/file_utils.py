from pathlib import Path


def is_likely_binary(file_path: Path, check_bytes: int = 1024) -> bool:
    """Check a byte sample for NUL, propagating errors when the file cannot be read."""
    with file_path.open("rb") as handle:
        return b"\x00" in handle.read(check_bytes)
