from __future__ import annotations

from collections.abc import Sequence


class UnsupportedLanguagesError(ValueError):
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


def parse_cli_languages(
    raw_languages: str | None,
    *,
    supported_extensions: set[str],
) -> list[str] | None:
    if raw_languages is None:
        return None
    if raw_languages == "":
        return []
    return normalize_language_filter(
        raw_languages.split(","),
        supported_extensions=supported_extensions,
    )


def normalize_language_filter(
    languages: Sequence[str] | None,
    *,
    supported_extensions: set[str],
) -> list[str] | None:
    if languages is None:
        return None

    normalized = [language.strip().lower() for language in languages if language.strip()]
    unsupported = sorted(set(normalized) - supported_extensions)
    if unsupported:
        raise UnsupportedLanguagesError(
            unsupported=unsupported,
            supported=supported_extensions,
        )
    return normalized
