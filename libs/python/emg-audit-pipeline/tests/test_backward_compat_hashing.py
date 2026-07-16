"""Backward-compatibility gate for version-aware canonical hashing (FEAT-04-2).

THIS FILE IS A MERGE-BLOCKING GATE. Sprint 7 must not change the hash of any
existing Sprint 6 (version-1) audit record. Two invariants are pinned here:

1. The version-1 canonical payload is *byte-for-byte identical* to the Sprint 6
   canonicalization — no `schema_version` / `provenance` keys are added — so a
   record produced before Sprint 7 recomputes to the exact same `event_hash`.
2. A concrete golden hash for a fixed version-1 event, computed the way Sprint 6
   would have computed it, still matches under the Sprint 7 code.

If either assertion fails, a change has silently altered the hash of already
published, immutable audit records — which is forbidden. Do not "update" the
golden value to make this pass; fix the code so version-1 hashing is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from emg_audit_client import (
    EVENT_SCHEMA_VERSION_V1,
    EVENT_SCHEMA_VERSION_V2,
    ProvenanceRecord,
    SubmittedAuditEvent,
)
from emg_audit_pipeline import (
    InMemoryAuditEventStore,
    canonical_payload,
    recompute_event_hash,
)

SP = "emg-svc-identity"

# A fixed version-1 event and its golden hash, computed from the exact Sprint 6
# canonical key set. Pinning the literal value guards against any future change
# to the version-1 payload shape.
_FIXED = dict(
    event_id="evt-golden",
    source_principal="emg-svc-identity",
    sequence_number=1,
    timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
    ingest_time=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
    prev_hash="0" * 64,
)
_GOLDEN_V1_HASH = "8c38a4a444ddbcc5a1d85b484dbfcbb88942880e9affd90f4dd74a022dbce25d"


def _fixed_submitted() -> SubmittedAuditEvent:
    return SubmittedAuditEvent(
        event_id="evt-golden",
        actor="alice",
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        correlation_id="corr-1",
        source_system="identity",
        reason="",
        metadata={"k": "v"},
    )


def _sprint6_payload() -> str:
    """The exact canonical payload string the Sprint 6 code produced for the
    fixed event — the Sprint 6 key set, verbatim, with no version/provenance
    keys."""
    payload = {
        "event_id": "evt-golden",
        "source_principal": "emg-svc-identity",
        "sequence_number": 1,
        "timestamp": _FIXED["timestamp"].isoformat(),
        "ingest_time": _FIXED["ingest_time"].isoformat(),
        "actor": "alice",
        "actor_type": "human",
        "module": "identity",
        "action": "login",
        "outcome": "success",
        "correlation_id": "corr-1",
        "resource_type": None,
        "resource_id": None,
        "classification": "INTERNAL",
        "source_system": "identity",
        "source_component": None,
        "reason": "",
        "metadata": {"k": "v"},
        "prev_hash": "0" * 64,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_v1_canonical_payload_is_byte_identical_to_sprint6() -> None:
    new = canonical_payload(
        submitted=_fixed_submitted(),
        schema_version=EVENT_SCHEMA_VERSION_V1,
        **_FIXED,
    )
    assert new == _sprint6_payload()


def test_v1_golden_hash_is_unchanged() -> None:
    payload = canonical_payload(
        submitted=_fixed_submitted(),
        schema_version=EVENT_SCHEMA_VERSION_V1,
        **_FIXED,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == _GOLDEN_V1_HASH


def test_default_schema_version_is_v1_backward_compatible() -> None:
    """Calling canonical_payload with no schema_version (as Sprint 6 callers
    did) must yield the version-1 payload."""
    default = canonical_payload(submitted=_fixed_submitted(), **_FIXED)
    explicit_v1 = canonical_payload(
        submitted=_fixed_submitted(), schema_version=EVENT_SCHEMA_VERSION_V1, **_FIXED
    )
    assert default == explicit_v1 == _sprint6_payload()


def test_v1_record_reverifies_under_v7_code() -> None:
    """A stored version-1 event recomputes to its stored hash under the Sprint 7
    version-aware verifier (the recompute path used by integrity checks)."""
    store = InMemoryAuditEventStore()
    e = store.append(_fixed_submitted(), source_principal=SP)
    assert e.schema_version == 1
    assert recompute_event_hash(e) == e.event_hash


def test_adding_provenance_produces_a_different_v2_hash() -> None:
    """Sanity: a version-2 event hashes differently (provenance is in the hash),
    so version-2 is a genuinely distinct, tamper-evident record — while version-1
    stays byte-identical."""
    prov = ProvenanceRecord(
        source_system="identity",
        originating_actor="alice",
        originating_principal=SP,
        event_time=datetime(2026, 7, 1, 11, 59, tzinfo=timezone.utc),
        ingest_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    v2 = canonical_payload(
        submitted=_fixed_submitted().model_copy(update={"provenance": prov}),
        schema_version=EVENT_SCHEMA_VERSION_V2,
        **_FIXED,
    )
    assert v2 != _sprint6_payload()
    assert '"provenance":' in v2
    assert '"schema_version":2' in v2


def test_mixed_v1_v2_chain_verifies_intact() -> None:
    """A store holding both version-1 and version-2 events verifies intact —
    each event recomputes against the exact payload version it was hashed
    with."""
    store = InMemoryAuditEventStore()
    prov = ProvenanceRecord(
        source_system="identity",
        originating_actor="alice",
        originating_principal=SP,
        event_time=datetime(2026, 7, 1, 11, 59, tzinfo=timezone.utc),
        ingest_time=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    store.append(_fixed_submitted().model_copy(update={"event_id": "v1a"}), source_principal=SP)
    store.append(
        _fixed_submitted().model_copy(update={"event_id": "v2a", "provenance": prov}),
        source_principal=SP,
    )
    store.append(_fixed_submitted().model_copy(update={"event_id": "v1b"}), source_principal=SP)
    report = store.verify_integrity()
    assert report.intact is True
    assert report.checked_count == 3
