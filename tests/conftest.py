from __future__ import annotations

from pathlib import Path

import repogpt

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"


def pytest_sessionstart(session: object) -> None:
    _ = session
    imported_from = Path(repogpt.__file__).resolve()
    if SRC_ROOT not in imported_from.parents:
        raise RuntimeError(
            f"repogpt imported from unexpected path: {imported_from}; expected under {SRC_ROOT}"
        )
