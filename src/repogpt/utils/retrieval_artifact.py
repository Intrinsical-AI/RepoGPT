from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repogpt.domain.code_units import KIND, SCHEMA_VERSION


def load_documents(path: Path) -> list[dict[str, Any]]:
    """Load code-units v5 inputs, rejecting malformed entries and duplicate identities."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != KIND
    ):
        raise ValueError("expected a code-units v5 object")
    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise ValueError("expected a documents array")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ValueError(f"documents[{index}] must be an object")
        for name in ("external_id", "container_id", "path", "qualified_name", "content"):
            value = document.get(name)
            if not isinstance(value, str) or (name != "content" and not value.strip()):
                expected = "string" if name == "content" else "non-empty string"
                raise ValueError(f"documents[{index}].{name} must be a {expected}")
        if "symbol" not in document or (
            document["symbol"] is not None and not isinstance(document["symbol"], str)
        ):
            raise ValueError(f"documents[{index}].symbol must be a string or null")
        external_id = document["external_id"]
        if external_id in seen:
            raise ValueError(f"duplicate external_id: {external_id}")
        seen.add(external_id)
        validated.append(document)
    return validated
