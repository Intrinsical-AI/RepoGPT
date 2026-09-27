from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from repogpt.domain.analysis import AstProjection, CodeUnitsProjection


class ArtifactWriter:
    def write(
        self,
        projection: AstProjection | CodeUnitsProjection,
        output_path: Path | None,
        *,
        format: Literal["json", "ndjson"] = "json",
    ) -> None:
        if output_path is None:
            self._write_stdout(projection, format)
            return

        temporary_path: Path | None = None
        try:
            try:
                mode = stat.S_IMODE(output_path.stat().st_mode)
            except FileNotFoundError:
                mode = None
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
                handle.flush()
            if mode is not None:
                temporary_path.chmod(mode)
            os.replace(temporary_path, output_path)
        except OSError as exc:
            raise OSError(
                exc.errno, f"failed to write artifact: {exc.strerror or exc}", str(output_path)
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

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
