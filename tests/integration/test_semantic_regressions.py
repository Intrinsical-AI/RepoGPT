from __future__ import annotations

import codecs
import hashlib
from pathlib import Path
from typing import Any, Literal

import pytest

from repogpt.domain.analysis import (
    AnalysisRequest,
    AnalysisResult,
)
from repogpt.runtime import build_analyze_repo
from repogpt.utils.retrieval_profiles import assemble_structured_bundle
from repogpt.utils.tree_utils import iter_nodes


def _analyze(
    tmp_path: Path, filename: str, source: str | bytes
) -> tuple[AnalysisResult, dict[str, Any]]:
    (tmp_path / filename).write_bytes(source.encode("utf-8") if isinstance(source, str) else source)
    result, projection = build_analyze_repo().run(
        AnalysisRequest(repo_root=tmp_path, projection="code_units")
    )
    return result, projection.json_payload


def test_python_control_flow_preserves_symbols_imports_and_scopes(tmp_path: Path) -> None:
    source = """class C:
    if flag:
        def first(self): pass
    elif other:
        def second(self): pass
    else:
        def third(self): pass
    try:
        import fast
    except ImportError:
        import slow
        def recover(self): pass
    else:
        def success(self): pass
    finally:
        def cleanup(self): pass
    match subject:
        case _:
            def dispatch(self):
                def nested(): pass
    for item in values:
        def loop(self): pass
    else:
        def exhausted(self): pass
"""
    result, payload = _analyze(tmp_path, "sample.py", source)
    assert result.stats.failed_files == 0
    names = [doc["qualified_name"] for doc in payload["documents"]]
    assert names == [
        "C",
        "C.first",
        "C.second",
        "C.third",
        "C.recover",
        "C.success",
        "C.cleanup",
        "C.dispatch",
        "C.dispatch.nested",
        "C.loop",
        "C.exhausted",
    ]
    root = result.parsed_files[0].root
    assert root is not None
    assert [
        node.attributes["imported_names"][0]["name"]
        for node in iter_nodes(root)
        if node.type == "import"
    ] == ["fast", "slow"]


def test_duplicate_python_declarations_survive_retrieval(tmp_path: Path) -> None:
    _, payload = _analyze(
        tmp_path,
        "sample.py",
        """class Demo:
    @property
    def value(self): return 1
    @value.setter
    def value(self, value): self._value = value
class Demo:
    def value(self): return 2
@overload
def f(x: int): ...
@overload
def f(x: str): ...
def f(x): return x
""",
    )
    docs = payload["documents"]
    names = [doc["qualified_name"] for doc in docs]
    assert names == [
        "Demo",
        "Demo.value",
        "Demo.value~2",
        "Demo~2",
        "Demo~2.value",
        "f",
        "f~2",
        "f~3",
    ]
    assert len({doc["external_id"] for doc in docs}) == len(docs)
    bundle = assemble_structured_bundle(docs, query_text="value", top_k=len(docs))
    assert len(bundle["items"]) == len(docs)
    assert docs[4]["container_id"] == docs[3]["external_id"]


def test_markdown_slugs_reserve_natural_suffixes(tmp_path: Path) -> None:
    _, payload = _analyze(tmp_path, "sample.md", "# A\n# A\n## Child\n```py\nx\n```\n# A-2\n")
    docs = payload["documents"]
    assert [doc["qualified_name"] for doc in docs] == [
        "a",
        "a-3",
        "a-3/child",
        "a-3/child/code_block[1]",
        "a-2",
    ]
    assert len({doc["external_id"] for doc in docs}) == len(docs)
    assert docs[3]["container_id"] == docs[2]["external_id"]


def test_markdown_preamble_and_root_heading_have_independent_code_identities(
    tmp_path: Path,
) -> None:
    heading = "# Root\n```py\nheading_code = 1\n```\n"
    _, original = _analyze(tmp_path, "sample.md", heading)
    _, prefixed = _analyze(tmp_path, "sample.md", "```py\npreamble = 1\n```\n" + heading)
    original_code = next(doc for doc in original["documents"] if doc["unit_type"] == "code_block")
    codes = [doc for doc in prefixed["documents"] if doc["unit_type"] == "code_block"]

    assert codes[1]["external_id"] == original_code["external_id"]
    assert codes[1]["qualified_name"] == original_code["qualified_name"]
    assert codes[0]["external_id"] != original_code["external_id"]
    assert codes[0]["container_id"].endswith(":module")
    assert codes[1]["container_id"].endswith(":heading:root")


@pytest.mark.parametrize(
    "prefix", ['payload = "a\u2028b"', "# page\fbreak", "# separator\u0085text"]
)
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_spans_use_python_physical_lines(tmp_path: Path, prefix: str, newline: str) -> None:
    expected = f"def f():{newline}    # inside{newline}    return 1{newline}"
    result, payload = _analyze(tmp_path, "sample.py", prefix + newline + expected)
    doc = payload["documents"][0]
    assert (doc["start_line"], doc["end_line"], doc["content"]) == (2, 4, expected)
    assert doc["content_hash"] == hashlib.sha256(expected.encode("utf-8")).hexdigest()
    root = result.parsed_files[0].root
    assert root is not None and root.end_line == 4
    function = root.children[0]
    assert function.comments == [{"text": "inside", "line": 3}]


@pytest.mark.parametrize(
    "source",
    [
        codecs.BOM_UTF8 + 'def f():\n    return "café"\n'.encode(),
        '# coding: latin-1\ndef f():\n    return "café"\n'.encode("latin-1"),
    ],
)
def test_python_valid_encoding_is_preserved(tmp_path: Path, source: bytes) -> None:
    result, payload = _analyze(tmp_path, "sample.py", source)
    assert result.stats.failed_files == 0
    doc = payload["documents"][0]
    assert doc["content"] == 'def f():\n    return "café"\n'
    assert doc["metadata"]["file"]["sha256"] == hashlib.sha256(source).hexdigest()


@pytest.mark.parametrize(
    "source", [b'def f():\n    return "\xff"\n', b"# coding: nonexistent\nx = 1\n"]
)
def test_invalid_python_encoding_is_a_file_failure(tmp_path: Path, source: bytes) -> None:
    result, payload = _analyze(tmp_path, "sample.py", source)
    assert result.stats.failed_files == 1
    assert payload["documents"] == []
    assert payload["failures"][0]["file"]["sha256"] == hashlib.sha256(source).hexdigest()


@pytest.mark.parametrize("fence,indent", [("````", ""), ("~~~~", "   ")])
def test_markdown_fences_require_a_valid_closing_fence(
    tmp_path: Path, fence: str, indent: str
) -> None:
    shorter = fence[:3]
    source = (
        f"{indent}{fence} markdown\n{shorter}\n# hidden\n"
        f"{fence}invalid\n{indent}{fence}  \n# visible\n"
    )
    result, _ = _analyze(tmp_path, "sample.md", source)
    root = result.parsed_files[0].root
    assert root is not None
    nodes = iter_nodes(root)
    assert [node.name for node in nodes if node.type == "heading"] == ["visible"]
    block = next(node for node in nodes if node.type == "code_block")
    assert (block.start_line, block.end_line, block.attributes["fence_language"]) == (
        1,
        5,
        "markdown",
    )


def test_markdown_links_on_same_line_have_distinct_ids(tmp_path: Path) -> None:
    result, _ = _analyze(
        tmp_path, "sample.md", "[Docs](https://one.invalid) [Docs](https://two.invalid)\n"
    )
    root = result.parsed_files[0].root
    assert root is not None
    links = root.children
    assert len({link.id for link in links}) == 2
    assert [link.attributes["start_column"] for link in links] == [0, 28]


def test_relative_import_level_is_preserved(tmp_path: Path) -> None:
    result, _ = _analyze(
        tmp_path,
        "sample.py",
        "from pkg import item\nfrom .pkg import item\nfrom ..pkg import item\nfrom . import item\n",
    )
    root = result.parsed_files[0].root
    assert root is not None
    assert [node.attributes["import_level"] for node in root.children] == [0, 1, 2, 1]
    assert [node.attributes["is_relative"] for node in root.children] == [False, True, True, True]


@pytest.mark.parametrize("projection", ["ast", "code_units"])
@pytest.mark.parametrize(
    "source",
    [
        "import os; import os as other\n",
        "from os import path; from os import environ\n",
        "def f():\n    from .pkg import item; from ..pkg import other\n",
    ],
)
def test_same_line_python_imports_do_not_abort_export(
    tmp_path: Path, projection: Literal["ast", "code_units"], source: str
) -> None:
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    result, artifact = build_analyze_repo().run(
        AnalysisRequest(repo_root=tmp_path, projection=projection)
    )

    assert result.stats.failed_files == 0
    assert artifact.json_payload
    root = result.parsed_files[0].root
    assert root is not None
    imports = [node for node in iter_nodes(root) if node.type == "import"]
    assert len(imports) == 2
    assert imports[0].start_line == imports[1].start_line
    assert imports[0].id != imports[1].id
