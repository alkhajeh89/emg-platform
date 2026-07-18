"""Reusable identifier/label validation (FEAT-13-1).

Every externally-supplied identifier and free-text label in a descriptor,
configuration, or plugin registration flows through `ensure_safe_label`. It
rejects empty/whitespace-only values and any NUL, ASCII control, CR/LF, or Unicode
bidirectional override/control character, while preserving legitimate Unicode. A
character allow/deny check only — no regex execution, no expression parsing — so a
malformed or hostile identifier is rejected at construction and there is no
injection surface. Exposed as pydantic `Annotated` types (`SafeLabel`, `SafeText`)
so the same rule is applied everywhere by annotating a field's type.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field

from .limits import MAX_LABEL_LENGTH, MAX_TEXT_LENGTH

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


SafeLabel = Annotated[str, Field(max_length=MAX_LABEL_LENGTH), AfterValidator(ensure_safe_label)]
SafeText = Annotated[str, Field(max_length=MAX_TEXT_LENGTH), AfterValidator(ensure_safe_label)]
