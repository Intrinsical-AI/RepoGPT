from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

from repogpt.domain.analysis import AstProjection, CodeUnitsProjection
from repogpt.domain.errors import InvalidRequestError


def file_output_path(
    value: str,
    *,
    repo_root: Path,
    supported_extensions: set[str],
) -> Path:
    """Validate a file destination without following a leaf symlink.

    The parent must exist. Existing repository sources may never be replaced,
    including sources omitted by selection or fail-fast.
    """
    if not value.strip() or value in {"-", "/dev/stdin", "/dev/stdout", "/dev/stderr"}:
        raise InvalidRequestError("output_path must name an artifact file, not standard I/O")
    candidate = Path(value)
    try:
        destination = candidate.parent.resolve(strict=True) / candidate.name
    except OSError as exc:
        raise OSError(exc.errno, "failed to resolve artifact destination", str(candidate)) from exc
    try:
        mode = destination.lstat().st_mode
    except FileNotFoundError:
        return destination
    if not stat.S_ISREG(mode):
        raise InvalidRequestError("output_path must be a regular file or a new file")
    if destination.suffix.lstrip(
        "."
    ).lower() in supported_extensions and destination.is_relative_to(repo_root.resolve()):
        raise InvalidRequestError("output_path must not overwrite a repository source file")
    return destination


@dataclass(frozen=True)
class ArtifactWriteReceipt:
    size_bytes: int
    sha256: str


class ArtifactWriter:
    @overload
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: Path,
        *,
        format: Literal["json", "ndjson"] = "json",
        receipt_check: Callable[[ArtifactWriteReceipt], None] | None = None,
    ) -> ArtifactWriteReceipt: ...

    @overload
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: None,
        *,
        format: Literal["json", "ndjson"] = "json",
        receipt_check: Callable[[ArtifactWriteReceipt], None] | None = None,
    ) -> None: ...

    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: Path | None,
        *,
        format: Literal["json", "ndjson"] = "json",
        receipt_check: Callable[[ArtifactWriteReceipt], None] | None = None,
    ) -> ArtifactWriteReceipt | None:
        """Publish synchronized bytes only after an optional receipt check succeeds.

        A rejected file receipt preserves the destination and removes temporary
        bytes. Standard output has no publication receipt.
        """
        if output_path is None:
            self._write_stdout(projection, format)
            return None

        temporary_path: Path | None = None
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            try:
                mode = stat.S_IMODE(output_path.stat().st_mode)
            except FileNotFoundError:
                current_umask = os.umask(0)
                os.umask(current_umask)
                mode = 0o666 & ~current_umask
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                delete=False,
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp",
            ) as handle:
                temporary_path = Path(handle.name)
                for chunk in self._chunks(projection, format):
                    handle.write(chunk)
                    encoded = chunk.encode("utf-8")
                    digest.update(encoded)
                    size_bytes += len(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            receipt = ArtifactWriteReceipt(size_bytes=size_bytes, sha256=digest.hexdigest())
            if receipt_check is not None:
                receipt_check(receipt)
            temporary_path.chmod(mode)
            os.replace(temporary_path, output_path)
        except OSError as exc:
            raise OSError(
                exc.errno, f"failed to write artifact: {exc.strerror or exc}", str(output_path)
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return receipt

    def _write_stdout(
        self,
        projection: AstProjection | CodeUnitsProjection,
        format: Literal["json", "ndjson"],
    ) -> None:
        for chunk in self._chunks(projection, format):
            sys.stdout.write(chunk)
        sys.stdout.flush()

    def _chunks(
        self,
        projection: AstProjection | CodeUnitsProjection,
        format: Literal["json", "ndjson"],
    ) -> Iterator[str]:
        if isinstance(projection, AstProjection) and format == "ndjson":
            for record in projection.ndjson_records:
                yield json.dumps(record, ensure_ascii=False) + "\n"
            return
        yield json.dumps(projection.json_payload, ensure_ascii=False, indent=2) + "\n"
