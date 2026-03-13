from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import repogpt  # noqa: E402


def pytest_sessionstart(session: object) -> None:
    _ = session
    imported_from = Path(repogpt.__file__).resolve()
    if SRC_ROOT not in imported_from.parents:
        raise RuntimeError(
            f"repogpt imported from unexpected path: {imported_from}; expected under {SRC_ROOT}"
        )
