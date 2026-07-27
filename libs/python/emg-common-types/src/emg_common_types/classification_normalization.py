"""Shared `classification_clearance` normalization helper (ADR-026 final
blocker fix).

This module deliberately does NOT live in `classification.py` — that module
defines the canonical `Classification` enum only and is out of scope for this
change. This module only *imports* `Classification`; it never redefines or
extends the enum itself.

Problem this closes: every inbound `classification_clearance` normalization
boundary across the platform (human login, legacy session, and each
service's inbound service-token validation) previously only checked "is this
a non-blank string?" before accepting the value verbatim. An unrecognized
string — `"banana"`, `"SUPER_SECRET"`, or any other value that is not one of
the four canonical `Classification` members — survived normalization
unchanged. Because `PolicyRule.required_attributes`/
`required_resource_attributes` matching (`emg_policy_engine`) is exact
allow-list matching with no "unrecognized value" special case, an
unrecognized `classification_clearance` string satisfies none of the
policy's per-classification deny rules — silently bypassing classification
enforcement rather than falling safely to the lowest clearance.

`normalize_classification_clearance` is the single, shared fix: it validates
the incoming value against the canonical `Classification` enum and only ever
returns one of its four members' string values, defaulting to
`Classification.UNCLASSIFIED.value` for anything missing, blank,
whitespace-only, non-string, or not a recognized enum member. Every
normalization boundary in the platform should call this one helper rather
than re-implement the check locally.
"""

from __future__ import annotations

from .classification import Classification


def normalize_classification_clearance(value: object) -> str:
    """Normalize an arbitrary inbound value into a canonical
    `Classification` string.

    Returns the matching `Classification` member's value unchanged for any
    recognized member (by value, e.g. `"SECRET"` -> `"SECRET"`). Returns
    `Classification.UNCLASSIFIED.value` for anything missing, blank,
    whitespace-only, not a string, or not a recognized `Classification`
    member — this is the platform's single definition of "unresolved
    clearance," replacing every ad-hoc truthy-string check that previously
    existed at each normalization boundary.
    """
    if isinstance(value, str) and value.strip():
        try:
            return Classification(value).value
        except ValueError:
            return Classification.UNCLASSIFIED.value
    return Classification.UNCLASSIFIED.value
