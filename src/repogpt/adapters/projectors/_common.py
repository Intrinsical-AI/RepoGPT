"""Shared projector records."""

from typing import Any

from repogpt.domain.files import FileDigest, ParsedFile


def file_digest(digest: FileDigest, *, sha_first: bool = False) -> dict[str, int | str]:
    if sha_first:
        return {"sha256": digest.sha256, "size": digest.size}
    return {"size": digest.size, "sha256": digest.sha256}


def failure_record(parsed_file: ParsedFile, *, schema_version: str) -> dict[str, Any]:
    assert parsed_file.failure is not None
    return {
        "record_type": "failure",
        "schema_version": schema_version,
        "path": parsed_file.relative_path,
        "language": parsed_file.language,
        "error": parsed_file.failure.message,
        "file": file_digest(parsed_file.digest),
    }
