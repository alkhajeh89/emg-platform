"""Deterministic unit coverage for the accepted evidence-ledger contract."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from inspect import signature

import pytest
from emg_memory_graph import EvidenceRef, EvidenceSource, Metadata
from emg_persistence import EvidenceLedgerIntegrityError, PersistenceError
from emg_persistence.evidence import (
    GENESIS_PREV_HASH,
    EvidenceEntry,
    EvidenceLedgerRepository,
    canonical_datetime,
    canonical_evidence_entry,
    canonical_evidence_payload,
    compute_evidence_entry_hash,
    inspect_persisted_entry,
    verify_evidence_entry,
)
from emg_platform_core import TenantId

TENANT = TenantId.of("tenant-a")
TENANT_B = TenantId.of("tenant-b")
CAPTURED_AT = datetime(2026, 8, 2, 8, 30, tzinfo=timezone.utc)


def _evidence(*, captured_at: datetime = CAPTURED_AT) -> EvidenceRef:
    return EvidenceRef.create(
        source=EvidenceSource.PDF,
        locator="evidence/وثيقة-1.pdf",
        source_principal="svc-ingest",
        captured_at=captured_at,
        description="Authoritative وثيقة",
        event_id="event-1",
        correlation_id="correlation-1",
        metadata=Metadata.from_mapping({"alpha": "one", "zulu": "اثنان"}),
    )


def _raw_values(evidence: EvidenceRef) -> dict[str, object]:
    return {
        "tenant": TENANT,
        "seq": 1,
        "prev_hash": GENESIS_PREV_HASH,
        "entry_hash": compute_evidence_entry_hash(
            tenant=TENANT,
            seq=1,
            prev_hash=GENESIS_PREV_HASH,
            evidence=evidence,
        ),
        "evidence_id": str(evidence.evidence_id),
        "source": evidence.source.value,
        "locator": str(evidence.locator),
        "source_principal": str(evidence.source_principal),
        "captured_at": CAPTURED_AT,
        "payload": canonical_evidence_payload(evidence),
    }


def test_canonical_serialization_is_exact_stable_and_jsonb_invariant() -> None:
    evidence = _evidence()
    canonical = canonical_evidence_entry(
        tenant=TENANT,
        seq=1,
        prev_hash=GENESIS_PREV_HASH,
        evidence=evidence,
    )
    parsed = json.loads(canonical)

    assert set(parsed) == {
        "captured_at",
        "evidence_id",
        "locator",
        "payload",
        "prev_hash",
        "seq",
        "source",
        "source_principal",
        "tenant_id",
    }
    assert "entry_hash" not in parsed
    assert parsed["payload"]["metadata"] == {"alpha": "one", "zulu": "اثنان"}
    assert canonical == json.dumps(
        json.loads(json.dumps(parsed, ensure_ascii=False)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert (
        compute_evidence_entry_hash(
            tenant=TENANT,
            seq=1,
            prev_hash=GENESIS_PREV_HASH,
            evidence=evidence,
        )
        == "c85ef73ccb5c028ad3c4e2a37c661a5eadab5093a787524c76ba3fe183d774ec"
    )


def test_datetime_normalization_is_identical_for_equivalent_instants() -> None:
    naive = datetime(2026, 8, 2, 8, 30)
    utc = naive.replace(tzinfo=timezone.utc)
    non_utc = datetime(2026, 8, 2, 12, 30, tzinfo=timezone(timedelta(hours=4)))

    assert canonical_datetime(naive) == canonical_datetime(utc) == canonical_datetime(non_utc)
    hashes = {
        compute_evidence_entry_hash(
            tenant=TENANT,
            seq=1,
            prev_hash=GENESIS_PREV_HASH,
            evidence=_evidence(captured_at=value),
        )
        for value in (naive, utc, non_utc)
    }
    assert len(hashes) == 1


def test_absent_optional_fields_are_explicit_json_nulls() -> None:
    evidence = EvidenceRef.create(
        source=EvidenceSource.EMAIL,
        locator="message-1",
        source_principal="svc-mail",
        captured_at=CAPTURED_AT,
    )

    payload = canonical_evidence_payload(evidence)

    assert payload["description"] is None
    assert payload["event_id"] is None
    assert payload["correlation_id"] is None
    assert payload["metadata"] == {}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("tenant", TENANT_B),
        ("seq", 2),
        ("prev_hash", "1" * 64),
        ("evidence_id", "other-evidence"),
        ("source", EvidenceSource.EMAIL.value),
        ("locator", "other-locator"),
        ("source_principal", "other-principal"),
        ("captured_at", CAPTURED_AT + timedelta(seconds=1)),
    ],
)
def test_altering_any_promoted_or_chain_field_is_detected(field: str, replacement: object) -> None:
    values = _raw_values(_evidence())
    values[field] = replacement

    entry, failure = inspect_persisted_entry(**values)  # type: ignore[arg-type]

    assert entry is None
    assert failure is not None


def test_altering_payload_or_inserting_float_is_detected() -> None:
    values = _raw_values(_evidence())
    payload = dict(values["payload"])  # type: ignore[arg-type]
    payload["description"] = "altered"
    values["payload"] = payload
    assert inspect_persisted_entry(**values)[0] is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "replacement", "expected_kind"),
    [
        ("prev_hash", "", "prev_hash"),
        ("entry_hash", "A" * 64, "entry_hash"),
        ("entry_hash", "a" * 63, "entry_hash"),
    ],
)
def test_noncanonical_hash_representations_are_rejected(
    field: str, replacement: object, expected_kind: str
) -> None:
    values = _raw_values(_evidence())
    values[field] = replacement

    entry, failure = inspect_persisted_entry(**values)  # type: ignore[arg-type]

    assert entry is None
    assert failure is not None
    assert failure.value == expected_kind

    values = _raw_values(_evidence())
    payload = dict(values["payload"])  # type: ignore[arg-type]
    payload["metadata"] = {"unsafe": 0.1}
    values["payload"] = payload
    assert inspect_persisted_entry(**values)[0] is None  # type: ignore[arg-type]


def test_payload_promoted_column_divergence_is_detected_even_with_matching_hash() -> None:
    evidence = _evidence()
    values = _raw_values(evidence)
    values["locator"] = "promoted-only-locator"
    canonical = json.dumps(
        {
            "captured_at": canonical_datetime(CAPTURED_AT),
            "evidence_id": values["evidence_id"],
            "locator": values["locator"],
            "payload": values["payload"],
            "prev_hash": values["prev_hash"],
            "seq": values["seq"],
            "source": values["source"],
            "source_principal": values["source_principal"],
            "tenant_id": TENANT.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    import hashlib

    values["entry_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    entry, failure = inspect_persisted_entry(**values)  # type: ignore[arg-type]

    assert entry is None
    assert failure is not None


def test_genesis_and_duplicate_capture_have_distinct_chain_identity() -> None:
    evidence = _evidence()
    first_hash = compute_evidence_entry_hash(
        tenant=TENANT,
        seq=1,
        prev_hash=GENESIS_PREV_HASH,
        evidence=evidence,
    )
    second_hash = compute_evidence_entry_hash(
        tenant=TENANT,
        seq=2,
        prev_hash=first_hash,
        evidence=evidence,
    )

    assert len(first_hash) == len(second_hash) == 64
    assert first_hash != second_hash
    assert first_hash.islower() and second_hash.islower()


def test_corrupt_entry_raises_distinct_non_retryable_integrity_error() -> None:
    evidence = _evidence()
    entry = EvidenceEntry(
        tenant_id=TENANT,
        seq=1,
        prev_hash=GENESIS_PREV_HASH,
        entry_hash="a" * 64,
        evidence=evidence,
    )

    with pytest.raises(EvidenceLedgerIntegrityError, match="tenant-a.*seq 1") as caught:
        verify_evidence_entry(entry)

    assert isinstance(caught.value, PersistenceError)
    assert "Authoritative" not in str(caught.value)
    assert "وثيقة" not in str(caught.value)


def test_repository_contract_is_internal_tenant_scoped_and_append_only() -> None:
    import emg_persistence

    assert "EvidenceLedgerRepository" not in emg_persistence.__all__
    assert set(EvidenceLedgerRepository.__dict__) >= {
        "append",
        "get",
        "list_range",
        "verify_range",
    }
    assert not {"update", "delete", "truncate", "repair"}.intersection(
        EvidenceLedgerRepository.__dict__
    )
    for method_name in ("append", "get", "list_range", "verify_range"):
        parameters = signature(getattr(EvidenceLedgerRepository, method_name)).parameters
        assert "tenant" in parameters
        assert not {"principal", "clearance", "policy", "authorization"}.intersection(parameters)
