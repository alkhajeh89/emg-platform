"""ADR-042 deterministic, locale-independent governed-search normalization."""

from __future__ import annotations

import unicodedata

SEARCH_NORMALIZER_VERSION = 1
MAX_SEARCH_QUERY_SCALARS = 128
MAX_SEARCH_QUERY_BYTES = 512


def normalize_search_text(value: str) -> str:
    """NFKC + Unicode casefold + governed whitespace collapse."""
    if not isinstance(value, str):
        raise ValueError("search text must be a string")
    if any(
        ord(char) == 0 or (unicodedata.category(char) == "Cc" and not char.isspace())
        for char in value
    ):
        raise ValueError("search text contains a prohibited control character")
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized:
        raise ValueError("search text must not be empty")
    if len(normalized) > MAX_SEARCH_QUERY_SCALARS:
        raise ValueError("normalized search text exceeds 128 Unicode scalar values")
    if len(normalized.encode("utf-8")) > MAX_SEARCH_QUERY_BYTES:
        raise ValueError("normalized search text exceeds 512 UTF-8 bytes")
    return normalized
