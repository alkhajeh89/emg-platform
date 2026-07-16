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
    MAX_PROVENANCE_PARENT_REFS,
    MAX_PROVENANCE_TRANSFORMATIONS,
    MAX_PROVENANCE_VALUE_LEN,
    ProvenanceRecord,
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


def _bounded(field: str, value: str | None, error_code: str) -> None:
    """Reject an over-long provenance free-text value."""
    if value is not None and len(value) > MAX_PROVENANCE_VALUE_LEN:
        raise ValidationError(
            f"provenance field {field!r} is {len(value)} chars; "
            f"maximum is {MAX_PROVENANCE_VALUE_LEN}",
            error_code=error_code,
        )


def _redact_opt(value: str | None) -> str | None:
    return None if value is None else redact_text(value)


def validate_and_sanitize_provenance(provenance: ProvenanceRecord) -> ProvenanceRecord:
    """Validate and redact a provenance record before persistence (FEAT-04-2).

    Same posture as metadata: bound the size (transformation history and
    parent-reference counts, and free-text field lengths) so a producer cannot
    smuggle a large payload through provenance, and redact secret-shaped
    substrings from free-text fields. Raises `emg_errors.ValidationError` on a
    bound violation. Structured identifiers (source system, principals, actor)
    are not free text and are only length-bounded, not redacted.
    """
    if len(provenance.transformation_history) > MAX_PROVENANCE_TRANSFORMATIONS:
        raise ValidationError(
            f"provenance transformation_history has {len(provenance.transformation_history)} "
            f"entries; maximum is {MAX_PROVENANCE_TRANSFORMATIONS}",
            error_code="AUDIT_PROVENANCE_HISTORY_TOO_LARGE",
        )
    if len(provenance.parent_event_refs) > MAX_PROVENANCE_PARENT_REFS:
        raise ValidationError(
            f"provenance parent_event_refs has {len(provenance.parent_event_refs)} "
            f"entries; maximum is {MAX_PROVENANCE_PARENT_REFS}",
            error_code="AUDIT_PROVENANCE_PARENTS_TOO_LARGE",
        )

    _bounded("source_system", provenance.source_system, "AUDIT_PROVENANCE_VALUE_TOO_LONG")
    _bounded("source_component", provenance.source_component, "AUDIT_PROVENANCE_VALUE_TOO_LONG")
    _bounded("originating_actor", provenance.originating_actor, "AUDIT_PROVENANCE_VALUE_TOO_LONG")
    _bounded(
        "originating_principal",
        provenance.originating_principal,
        "AUDIT_PROVENANCE_VALUE_TOO_LONG",
    )
    _bounded("evidence_origin", provenance.evidence_origin, "AUDIT_PROVENANCE_VALUE_TOO_LONG")
    _bounded("collection_method", provenance.collection_method, "AUDIT_PROVENANCE_VALUE_TOO_LONG")
    for step in provenance.transformation_history:
        _bounded("transformation.detail", step.detail, "AUDIT_PROVENANCE_VALUE_TOO_LONG")

    redacted_history = tuple(
        step.model_copy(update={"detail": redact_text(step.detail)})
        for step in provenance.transformation_history
    )
    return provenance.model_copy(
        update={
            "evidence_origin": _redact_opt(provenance.evidence_origin),
            "collection_method": _redact_opt(provenance.collection_method),
            "transformation_history": redacted_history,
        }
    )


def validate_and_sanitize(event: SubmittedAuditEvent) -> SubmittedAuditEvent:
    """Reject an event that violates the Sprint 6 security requirements, and
    return a sanitized copy with `reason`, metadata values, and provenance
    free-text redacted.

    Raises `emg_errors.ValidationError` for:
    - a metadata key whose name looks sensitive (potential secret leakage),
    - too many metadata entries, or a metadata value that is too long,
    - oversized provenance (FEAT-04-2).
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
    update: dict[str, object] = {
        "reason": redact_text(event.reason),
        "metadata": sanitized_metadata,
    }
    if event.provenance is not None:
        update["provenance"] = validate_and_sanitize_provenance(event.provenance)
    return event.model_copy(update=update)
