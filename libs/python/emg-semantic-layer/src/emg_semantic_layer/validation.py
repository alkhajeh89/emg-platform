"""Reusable string/identifier validation (FEAT-05-4).

Every externally-supplied identifier and label in the query model — node/
relationship ids, entity/type names, relationship-type names, filter field names,
projection fields, ordering fields, and property keys — flows through
`ensure_safe_label`. It rejects empty/whitespace-only values and any string
carrying NUL, ASCII control, CR/LF, or Unicode bidirectional override/control
characters, while preserving legitimate Unicode text.

This is deliberately a **character allow/deny check only** — no regex execution,
no expression parsing, no normalisation that could itself be surprising. It
exists so a malformed or hostile label (a control-character or bidi-spoofed
identifier) is rejected at query construction, long before any storage binding
turns a label into a query.

Exposed as a pydantic `AfterValidator` (`SafeLabel`) so the exact same rule is
applied everywhere by annotating a field's type, never by duplicating logic.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator

# Unicode bidirectional formatting characters (overrides, embeddings, isolates,
# and marks). These are the classic identifier-spoofing vector and are never
# legitimate inside a graph label, so they are rejected explicitly. ASCII control
# characters (including NUL, CR, and LF) are caught by the general-category check
# below (category "Cc"), so they are not enumerated here.
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
    # "Cc" == control characters (U+0000–U+001F, U+007F–U+009F), which includes
    # NUL, CR (\r), and LF (\n). Bidi controls are category "Cf" (format), so they
    # are checked against the explicit set above rather than by category.
    return unicodedata.category(ch) == "Cc" or ch in _BIDI_CONTROL_CHARS


def ensure_safe_label(value: str) -> str:
    """Return `value` unchanged if it is a safe label; otherwise raise
    `ValueError`. Rejects empty/whitespace-only strings and any NUL, ASCII
    control, CR/LF, or Unicode bidi override/control character."""
    if not value or not value.strip():
        raise ValueError("must be a non-empty, non-whitespace string")
    forbidden = sorted({f"U+{ord(ch):04X}" for ch in value if _is_forbidden_char(ch)})
    if forbidden:
        raise ValueError(f"contains disallowed control/bidi characters: {forbidden}")
    return value


# A `str` field type that is validated by `ensure_safe_label` after coercion.
# Annotate any identifier/label field (or the element type of a tuple of labels)
# with `SafeLabel` to apply the rule uniformly.
SafeLabel = Annotated[str, AfterValidator(ensure_safe_label)]
