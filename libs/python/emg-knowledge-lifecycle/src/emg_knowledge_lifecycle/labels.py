"""Reusable identifier/label validation (FEAT-05-5).

Every externally-supplied identifier and free-text label (entity ids, actor ids,
metadata author/note) flows through `ensure_safe_label` / `ensure_safe_text`.
They reject empty/whitespace-only values and any string carrying NUL, ASCII
control, CR/LF, or Unicode bidirectional override/control characters, while
preserving legitimate Unicode text. This is a character allow/deny check only —
no regex execution, no expression parsing — so a malformed or hostile identifier
is rejected at construction, and there is no injection surface.

Exposed as pydantic `AfterValidator` types (`SafeLabel`, `SafeText`) so the same
rule is applied everywhere by annotating a field's type.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field

from .limits import MAX_LABEL_LENGTH, MAX_TEXT_LENGTH

# Unicode bidirectional formatting characters (overrides, embeddings, isolates,
# and marks) — the classic identifier-spoofing vector. ASCII control characters
# (NUL, CR, LF, ...) are caught by the general-category check below.
_BIDI_CONTROL_CHARS: frozenset[str] = frozenset(
    {
        "‪",  # LEFT-TO-RIGHT EMBEDDING
        "‫",  # RIGHT-TO-LEFT EMBEDDING
        "‬",  # POP DIRECTIONAL FORMATTING
        "‭",  # LEFT-TO-RIGHT OVERRIDE
        "‮",  # RIGHT-TO-LEFT OVERRIDE
        "⁦",  # LEFT-TO-RIGHT ISOLATE
        "⁧",  # RIGHT-TO-LEFT ISOLATE
        "⁨",  # FIRST STRONG ISOLATE
        "⁩",  # POP DIRECTIONAL ISOLATE
        "‎",  # LEFT-TO-RIGHT MARK
        "‏",  # RIGHT-TO-LEFT MARK
        "؜",  # ARABIC LETTER MARK
    }
)


def _is_forbidden_char(ch: str) -> bool:
    return unicodedata.category(ch) == "Cc" or ch in _BIDI_CONTROL_CHARS


def ensure_safe_label(value: str) -> str:
    """Return `value` unchanged if it is a safe identifier/label; otherwise raise
    `ValueError`. Rejects empty/whitespace-only strings and any NUL, ASCII
    control, CR/LF, or Unicode bidi override/control character."""
    if not value or not value.strip():
        raise ValueError("must be a non-empty, non-whitespace string")
    forbidden = sorted({f"U+{ord(ch):04X}" for ch in value if _is_forbidden_char(ch)})
    if forbidden:
        raise ValueError(f"contains disallowed control/bidi characters: {forbidden}")
    return value


# A validated identifier: safe characters, bounded length.
SafeLabel = Annotated[str, Field(max_length=MAX_LABEL_LENGTH), AfterValidator(ensure_safe_label)]

# Validated free text (metadata author/note): safe characters, bounded length.
SafeText = Annotated[str, Field(max_length=MAX_TEXT_LENGTH), AfterValidator(ensure_safe_label)]
