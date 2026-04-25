from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "tests" / "golden"
SCHEMA_ROOT = REPO_ROOT / "schemas"


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _validator(schema_name: str) -> Draft202012Validator:
    schema = _load_json(SCHEMA_ROOT / schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_ast_json_golden_matches_public_schema() -> None:
    validator = _validator("ast-v1.schema.json")
    validator.validate(_load_json(GOLDEN_ROOT / "cli_fixture_json.json"))


def test_ast_ndjson_golden_records_match_public_schema() -> None:
    validator = _validator("ast-v1.schema.json")
    records = [
        json.loads(line)
        for line in (GOLDEN_ROOT / "cli_fixture_ndjson.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    for record in records:
        validator.validate(record)


def test_code_units_json_golden_matches_public_schema() -> None:
    validator = _validator("code-units-v4.schema.json")
    validator.validate(_load_json(GOLDEN_ROOT / "cli_fixture_code_units.json"))
