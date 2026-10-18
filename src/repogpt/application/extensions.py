from __future__ import annotations

from collections.abc import Sequence


class UnsupportedExtensionsError(ValueError):
    def __init__(self, *, unsupported: list[str], supported: set[str]) -> None:
        self.unsupported = unsupported
        self.supported = supported
        super().__init__(self.message)

    @property
    def message(self) -> str:
        return (
            "unsupported languages: "
            + ", ".join(self.unsupported)
            + "; supported: "
            + ", ".join(sorted(self.supported))
        )


def parse_cli_extensions(
    raw_extensions: str | None,
    *,
    supported_extensions: set[str],
) -> list[str] | None:
    if raw_extensions is None:
        return None
    if raw_extensions == "":
        return []
    return normalize_extension_filter(
        raw_extensions.split(","),
        supported_extensions=supported_extensions,
    )


def normalize_extension_filter(
    extensions: Sequence[str] | None,
    *,
    supported_extensions: set[str],
) -> list[str] | None:
    if extensions is None:
        return None

    normalized = [extension.strip().lower() for extension in extensions if extension.strip()]
    unsupported = sorted(set(normalized) - supported_extensions)
    if unsupported:
        raise UnsupportedExtensionsError(
            unsupported=unsupported,
            supported=supported_extensions,
        )
    return normalized
