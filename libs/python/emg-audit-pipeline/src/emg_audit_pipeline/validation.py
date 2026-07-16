"""Pre-persistence validation and redaction for audit events (FEAT-04-1,
Sprint 6 security requirements).

Two guarantees enforced here before an event is ever stored:

1. **No secrets/tokens in an audit record.** Raw access tokens, refresh
   tokens, client secrets, passwords, and Authorization headers must never be
   persisted. This is enforced structurally (the `SubmittedAuditEvent` model
   has no token/secret field) and defensively here: metadata keys whose names
   look sensitive are rejected, and `reason`/metadata *values* are run through
   a best-effort redaction of secret-shaped substrings.
2. **Bounded metadata.** Metadata is size- and count-limited so a producer
   cannot smuggle a large or unbounded payload into the immutable store.

The redaction patterns mirror `services/identity/redact.py` (Sprint 3); they
are a defense-in-depth backstop, not the primary control (the primary control
is that no sink method accepts a raw secret).
"""

from __future__ import annotations

import re

from emg_audit_client import (
    MAX_METADATA_ENTRIES,
    MAX_METADATA_VALUE_LEN,
    SubmittedAuditEvent,
)
from emg_errors import ValidationError

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(secret|password|passwd|token|credential|authorization|bind_dn|private_key|api[_-]?key)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"
_SECRET_SUBSTRING_PATTERN = re.compile(
    r'("?(?:secret|password|token|authorization|api[_-]?key)"?\s*[:=]\s*")[^"]*(")',
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    """True if a metadata key name looks like it would hold a secret."""
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def redact_text(text: str) -> str:
    """Best-effort redaction of secret-shaped substrings and bearer tokens in
    free text before it is persisted to an audit record."""
    redacted = _SECRET_SUBSTRING_PATTERN.sub(r"\1" + _REDACTED + r"\2", text)
    redacted = _BEARER_PATTERN.sub("Bearer " + _REDACTED, redacted)
    return redacted


def validate_and_sanitize(event: SubmittedAuditEvent) -> SubmittedAuditEvent:
    """Reject an event that violates the Sprint 6 security requirements, and
    return a sanitized copy with `reason` and metadata values redacted.

    Raises `emg_errors.ValidationError` for:
    - a metadata key whose name looks sensitive (potential secret leakage),
    - too many metadata entries, or a metadata value that is too long.
    """
    if len(event.metadata) > MAX_METADATA_ENTRIES:
        raise ValidationError(
            f"audit event metadata has {len(event.metadata)} entries; "
            f"maximum is {MAX_METADATA_ENTRIES}",
            error_code="AUDIT_METADATA_TOO_LARGE",
        )

    for key, value in event.metadata.items():
        if is_sensitive_key(key):
            raise ValidationError(
                f"audit event metadata key {key!r} looks sensitive and may not "
                "be stored in an audit record",
                error_code="AUDIT_METADATA_SENSITIVE_KEY",
            )
        if len(value) > MAX_METADATA_VALUE_LEN:
            raise ValidationError(
                f"audit event metadata value for {key!r} is {len(value)} chars; "
                f"maximum is {MAX_METADATA_VALUE_LEN}",
                error_code="AUDIT_METADATA_VALUE_TOO_LONG",
            )

    sanitized_metadata = {key: redact_text(value) for key, value in event.metadata.items()}
    return event.model_copy(
        update={"reason": redact_text(event.reason), "metadata": sanitized_metadata}
    )
