"""Pre-persistence validation and redaction (FEAT-04-1 Sprint 6 security):
no secrets/tokens in audit records, bounded metadata, sensitive-key
rejection."""

from __future__ import annotations

import pytest
from emg_audit_client import MAX_METADATA_ENTRIES
from emg_audit_pipeline import InMemoryAuditEventStore, redact_text, validate_and_sanitize
from emg_errors import ValidationError


def test_bearer_token_in_reason_is_redacted_before_persistence(make_submitted) -> None:
    store = InMemoryAuditEventStore()
    persisted = store.append(
        make_submitted("evt-1", reason="upstream said Authorization: Bearer abc.def.ghi"),
        source_principal="emg-svc-identity",
    )
    assert "abc.def.ghi" not in persisted.reason
    assert "REDACTED" in persisted.reason


def test_secret_shaped_substring_in_reason_is_redacted() -> None:
    result = redact_text('client_secret="s3cr3t-value"')
    assert "s3cr3t-value" not in result
    assert "REDACTED" in result


def test_sensitive_metadata_key_is_rejected(make_submitted) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_and_sanitize(make_submitted("evt-1", metadata={"password": "hunter2"}))
    assert exc.value.error_code == "AUDIT_METADATA_SENSITIVE_KEY"


def test_authorization_metadata_key_is_rejected(make_submitted) -> None:
    with pytest.raises(ValidationError):
        validate_and_sanitize(make_submitted("evt-1", metadata={"authorization": "Bearer x"}))


def test_too_many_metadata_entries_is_rejected(make_submitted) -> None:
    metadata = {f"k{i}": "v" for i in range(MAX_METADATA_ENTRIES + 1)}
    with pytest.raises(ValidationError) as exc:
        validate_and_sanitize(make_submitted("evt-1", metadata=metadata))
    assert exc.value.error_code == "AUDIT_METADATA_TOO_LARGE"


def test_oversized_metadata_value_is_rejected(make_submitted) -> None:
    with pytest.raises(ValidationError) as exc:
        validate_and_sanitize(make_submitted("evt-1", metadata={"note": "x" * 2000}))
    assert exc.value.error_code == "AUDIT_METADATA_VALUE_TOO_LONG"


def test_benign_metadata_is_preserved(make_submitted) -> None:
    event = validate_and_sanitize(
        make_submitted("evt-1", metadata={"department": "Investigations"})
    )
    assert event.metadata == {"department": "Investigations"}
