from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from jsonschema import Draft202012Validator, ValidationError

from repogpt.domain.analysis import AnalysisRequest, AstProjection
from repogpt.runtime import build_analyze_repo
from repogpt.utils.tree_utils import iter_nodes

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_ROOT = REPO_ROOT / "tests" / "golden"


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _validator(schema_name: str) -> Draft202012Validator:
    resource = files("repogpt").joinpath("schemas").joinpath(schema_name)
    schema = json.loads(resource.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_ast_json_golden_matches_public_schema() -> None:
    validator = _validator("ast-v3.schema.json")
    validator.validate(_load_json(GOLDEN_ROOT / "cli_fixture_json.json"))


def test_ast_ndjson_golden_records_match_public_schema() -> None:
    validator = _validator("ast-v3.schema.json")
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
    validator = _validator("code-units-v6.schema.json")
    validator.validate(_load_json(GOLDEN_ROOT / "cli_fixture_code_units.json"))


def test_code_units_v6_requires_module_only_content_ranges(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("CONSTANT = 3\ndef f():\n    pass\n", encoding="utf-8")
    _, projection = build_analyze_repo().run(
        AnalysisRequest(repo_root=tmp_path, projection="code_units", repo_key="schema-test")
    )
    payload = projection.json_payload
    validator = _validator("code-units-v6.schema.json")
    validator.validate(payload)

    without_ranges = json.loads(json.dumps(payload))
    without_ranges["documents"][0].pop("content_ranges")
    with pytest.raises(ValidationError):
        validator.validate(without_ranges)

    spurious_ranges = json.loads(json.dumps(payload))
    spurious_ranges["documents"][1]["content_ranges"] = []
    with pytest.raises(ValidationError):
        validator.validate(spurious_ranges)


@pytest.mark.parametrize("decorator", ["@\\\ndecorator\n", "@(\n    decorator\n)\n"])
def test_cli_multiline_decorators_validate_and_stay_with_the_callable(
    tmp_path: Path, decorator: str
) -> None:
    declaration = decorator + "async def f():\n    pass\n"
    (tmp_path / "sample.py").write_text("VALUE = 1\n" + declaration, encoding="utf-8")
    for projection, schema in [
        ("ast", "ast-v3.schema.json"),
        ("code-units", "code-units-v6.schema.json"),
    ]:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "repogpt.app.cli",
                str(tmp_path),
                "--emit",
                projection,
                "--stdout",
            ]
            + (["--repo-key", "decorator-test"] if projection == "code-units" else []),
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        payload = json.loads(process.stdout)
        _validator(schema).validate(payload)
        assert payload["stats"]["failed_files"] == 0
        if projection == "ast":
            function = next(node for node in payload["records"] if node["type"] == "function")
            assert (function["start_line"], function["start_column"]) == (2, 0)
        else:
            module, function = payload["documents"]
            assert module["content"] == "VALUE = 1\n"
            assert function["content"] == declaration
            assert function["start_line"] == 2


@pytest.mark.parametrize(
    "projection,format,flatten",
    [
        ("ast", "json", "file"),
        ("ast", "json", "node"),
        ("ast", "ndjson", "file"),
        ("ast", "ndjson", "node"),
        ("code_units", "json", "node"),
    ],
)
def test_fresh_semantic_regressions_match_public_schemas(
    tmp_path: Path,
    projection: Literal["ast", "code_units"],
    format: Literal["json", "ndjson"],
    flatten: Literal["node", "file"],
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.py").write_bytes(
        b"\xef\xbb\xbf"
        + (
            "class C:\n    if flag:\n        def f(self): pass\n    else:\n"
            '        def f(self): return "café"\nfrom ..pkg import item\n'
        ).encode()
    )
    (root / "sample.md").write_text(
        "# A\n# A\n[Docs](one) [Docs](two)\n````py\n```\n# hidden\n````\n# A-2\n",
        encoding="utf-8",
    )
    result, artifact = build_analyze_repo().run(
        AnalysisRequest(
            repo_root=root,
            projection=projection,
            format=format,
            flatten_kind=flatten,
            repo_key="schema-test" if projection == "code_units" else None,
            replace_scope=projection == "code_units",
            include_tests=True,
        )
    )
    assert result.stats.failed_files == 0
    schema = "code-units-v6.schema.json" if projection == "code_units" else "ast-v3.schema.json"
    validator = _validator(schema)
    if format == "ndjson":
        assert isinstance(artifact, AstProjection)
        for record in artifact.ndjson_records:
            validator.validate(record)
    else:
        validator.validate(artifact.json_payload)


@pytest.mark.parametrize("depth", [1, 2])
@pytest.mark.parametrize("child", [42, {"id": "incomplete"}])
def test_ast_schema_rejects_malformed_nested_nodes(depth: int, child: object) -> None:
    payload = _load_json(GOLDEN_ROOT / "cli_fixture_json.json")
    node = payload["records"][0]
    for _ in range(depth - 1):
        node = node["children"][0]
    node["children"] = [child]
    with pytest.raises(ValidationError):
        _validator("ast-v3.schema.json").validate(payload)


@pytest.fixture
def supported_parser_repo(tmp_path: Path) -> Path:
    (tmp_path / "sample.py").write_text(
        '"""Module documentation."""\n'
        "# Module comment\n"
        "import os as operating_system\n"
        "from ..package import item\n"
        "@decorator\n"
        "class C(Base):\n"
        "    def method(self, value: int = 1, /, extra='x', *args, flag=True, **kwargs) -> int:\n"
        '        """Method documentation."""\n'
        "        return value\n"
        "async def helper(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "sample.md").write_text(
        "Preamble\n<!-- TODO: document -->\n# Heading\n[Docs](u)\n"
        "```python\nprint('ok')\n```\n## Child\n~~~\nunclosed\n",
        encoding="utf-8",
    )
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    return tmp_path


def _object_paths(value: Any, path: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    paths: list[tuple[str | int, ...]] = []
    if isinstance(value, dict):
        paths.append(path)
        for key, child in value.items():
            paths.extend(_object_paths(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_object_paths(child, (*path, index)))
    return paths


@pytest.mark.parametrize(
    "projection,format,flatten",
    [
        ("ast", "json", "file"),
        ("ast", "json", "node"),
        ("ast", "ndjson", "file"),
        ("ast", "ndjson", "node"),
        ("code_units", "json", "node"),
    ],
)
def test_supported_exports_reject_extra_fields_at_every_object(
    supported_parser_repo: Path,
    projection: Literal["ast", "code_units"],
    format: Literal["json", "ndjson"],
    flatten: Literal["node", "file"],
) -> None:
    result, artifact = build_analyze_repo().run(
        AnalysisRequest(
            repo_root=supported_parser_repo,
            projection=projection,
            format=format,
            flatten_kind=flatten,
            repo_key="schema-test" if projection == "code_units" else None,
        )
    )
    assert result.stats.ok_files == 2
    assert result.stats.failed_files == 1
    assert {
        node.type
        for parsed_file in result.parsed_files
        if parsed_file.root is not None
        for node in iter_nodes(parsed_file.root)
    } == {"module", "import", "class", "method", "function", "heading", "link", "code_block"}
    schema = "code-units-v6.schema.json" if projection == "code_units" else "ast-v3.schema.json"
    validator = _validator(schema)
    if format == "ndjson":
        assert isinstance(artifact, AstProjection)
        payloads = list(artifact.ndjson_records)
        assert {record["record_type"] for record in payloads} == {"node", "failure", "summary"}
    else:
        payloads = [artifact.json_payload]
    for payload in payloads:
        validator.validate(payload)
        for path in _object_paths(payload):
            modified = deepcopy(payload)
            target: Any = modified
            for key in path:
                target = target[key]
            target["unexpected_field"] = True
            assert not validator.is_valid(modified), f"Unknown field accepted at {path}"


@pytest.mark.parametrize("field", ["path", "signature"])
def test_ast_schema_rejects_required_field_renames(supported_parser_repo: Path, field: str) -> None:
    _, artifact = build_analyze_repo().run(AnalysisRequest(repo_root=supported_parser_repo))
    payload = deepcopy(artifact.json_payload)
    function = next(node for node in payload["records"] if node["type"] == "function")
    target = function if field == "path" else function["attributes"]
    target[f"renamed_{field}"] = target.pop(field)

    with pytest.raises(ValidationError):
        _validator("ast-v3.schema.json").validate(payload)


def test_ast_schema_rejects_unknown_node_types(supported_parser_repo: Path) -> None:
    _, artifact = build_analyze_repo().run(AnalysisRequest(repo_root=supported_parser_repo))
    payload = deepcopy(artifact.json_payload)
    payload["records"][0]["type"] = "unsupported-parser-node"

    with pytest.raises(ValidationError):
        _validator("ast-v3.schema.json").validate(payload)


def test_code_units_metadata_does_not_repeat_empty_dependencies(
    supported_parser_repo: Path,
) -> None:
    _, artifact = build_analyze_repo().run(
        AnalysisRequest(repo_root=supported_parser_repo, projection="code_units")
    )

    assert all(
        "dependencies" not in document["metadata"]
        for document in artifact.json_payload["documents"]
    )


@pytest.mark.parametrize("field", ["path", "signature"])
def test_code_units_schema_rejects_required_field_renames(
    supported_parser_repo: Path, field: str
) -> None:
    _, artifact = build_analyze_repo().run(
        AnalysisRequest(repo_root=supported_parser_repo, projection="code_units")
    )
    payload = deepcopy(artifact.json_payload)
    function = next(
        document for document in payload["documents"] if document["unit_type"] == "function"
    )
    target = function if field == "path" else function["metadata"]["attributes"]
    target[f"renamed_{field}"] = target.pop(field)

    with pytest.raises(ValidationError):
        _validator("code-units-v6.schema.json").validate(payload)


def test_code_units_schema_rejects_unknown_unit_types(supported_parser_repo: Path) -> None:
    _, artifact = build_analyze_repo().run(
        AnalysisRequest(repo_root=supported_parser_repo, projection="code_units")
    )
    payload = deepcopy(artifact.json_payload)
    payload["documents"][0]["unit_type"] = "unsupported-parser-node"

    with pytest.raises(ValidationError):
        _validator("code-units-v6.schema.json").validate(payload)
