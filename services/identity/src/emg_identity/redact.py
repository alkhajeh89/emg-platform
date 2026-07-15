"""Secret redaction utility (Sprint 3 — Required Security Controls: "Secret
redaction in logs").

The primary control against secret leakage is structural: no function in
this service accepts a raw client secret or token as a loggable parameter
(`AuditEventSink`'s methods only take safe fields — see audit.py). This
module is the defense-in-depth backstop for the remaining case: free-text
error messages (e.g. a Keycloak error response body) that might incidentally
contain a secret-shaped value and get logged or returned to a caller.
"""

from __future__ import annotations

import re

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|password|passwd|token|credential|bind_dn|private_key)", re.IGNORECASE
)
_REDACTED = "***REDACTED***"


def is_sensitive_key(key: str) -> bool:
    """True if a config/claim key name looks like it holds a secret."""
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def redact_value(value: object) -> object:
    """Return a redacted placeholder for any non-empty scalar value."""
    if value is None or value == "":
        return value
    return _REDACTED


def redact_mapping(data: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy of `data` with sensitive-looking keys redacted.
    Used before logging or returning any dict that might originate from
    operator-supplied configuration (e.g. federation connection settings)."""
    return {
        key: (redact_value(value) if is_sensitive_key(key) else value)
        for key, value in data.items()
    }


def redact_text(text: str) -> str:
    """Best-effort redaction of secret-shaped substrings in free text (e.g.
    an upstream error message that echoed back a request body). This is a
    backstop, not a guarantee — call sites should prefer not to log
    raw upstream error bodies at all when a request could have carried a
    secret (see keycloak_client.py's error handling, which never logs
    request bodies)."""
    pattern = r'("?(?:secret|password|token)"?\s*[:=]\s*")[^"]*(")'
    replacement = r"\1" + _REDACTED + r"\2"
    return re.sub(pattern, replacement, text, flags=re.IGNORECASE)
