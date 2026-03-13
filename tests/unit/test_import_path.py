from __future__ import annotations

from pathlib import Path

import repogpt


def test_repogpt_imports_from_this_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src"
    imported_from = Path(repogpt.__file__).resolve()
    assert src_root in imported_from.parents
