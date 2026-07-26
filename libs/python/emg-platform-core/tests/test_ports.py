"""Storage-port contracts: WriteReceipt validation + structural conformance."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from _pc_helpers import sample_graph
from emg_platform_core import (
    SYSTEM_PRINCIPAL,
    SYSTEM_TENANT,
    GraphStore,
    GraphTransaction,
    InMemoryGraphStore,
    PrincipalRef,
    TenantId,
    WriteReceipt,
)
from pydantic import ValidationError

_HASH64 = "a" * 64
_COMMITTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_write_receipt_valid() -> None:
    r = WriteReceipt(
        tenant=TenantId.of("t"),
        principal=PrincipalRef.service("svc"),
        content_hash=_HASH64,
        node_count=2,
        edge_count=1,
        revision_number=1,
        committed_at=_COMMITTED_AT,
        revision_created=True,
    )
    assert r.node_count == 2 and r.edge_count == 1
    assert r.content_hash == _HASH64
    assert r.revision_number == 1
    assert r.committed_at == _COMMITTED_AT
    assert r.revision_created is True


def test_write_receipt_rejects_bad_hash_length() -> None:
    for bad in ("", "abc", "a" * 63, "a" * 65):
        with pytest.raises(ValidationError):
            WriteReceipt(
                tenant=TenantId.of("t"),
                principal=PrincipalRef.service("svc"),
                content_hash=bad,
                node_count=0,
                edge_count=0,
                revision_number=1,
                committed_at=_COMMITTED_AT,
                revision_created=True,
            )


def test_write_receipt_rejects_non_lowercase_hex_hash() -> None:
    # 64 chars but not lowercase hex must be rejected by the pattern.
    for bad in ("A" * 64, "g" * 64, "0" * 63 + "Z", "0" * 63 + " "):
        with pytest.raises(ValidationError):
            WriteReceipt(
                tenant=TenantId.of("t"),
                principal=PrincipalRef.service("svc"),
                content_hash=bad,
                node_count=0,
                edge_count=0,
                revision_number=1,
                committed_at=_COMMITTED_AT,
                revision_created=True,
            )


def test_write_receipt_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        WriteReceipt(
            tenant=TenantId.of("t"),
            principal=PrincipalRef.service("svc"),
            content_hash=_HASH64,
            node_count=-1,
            edge_count=0,
            revision_number=1,
            committed_at=_COMMITTED_AT,
            revision_created=True,
        )


def test_write_receipt_rejects_non_positive_revision_number() -> None:
    for bad_revision_number in (0, -1):
        with pytest.raises(ValidationError):
            WriteReceipt(
                tenant=TenantId.of("t"),
                principal=PrincipalRef.service("svc"),
                content_hash=_HASH64,
                node_count=0,
                edge_count=0,
                revision_number=bad_revision_number,
                committed_at=_COMMITTED_AT,
                revision_created=True,
            )


def test_write_receipt_is_frozen() -> None:
    r = WriteReceipt(
        tenant=TenantId.of("t"),
        principal=PrincipalRef.service("svc"),
        content_hash=_HASH64,
        node_count=0,
        edge_count=0,
        revision_number=1,
        committed_at=_COMMITTED_AT,
        revision_created=True,
    )
    with pytest.raises(ValidationError):
        r.node_count = 5  # type: ignore[misc]


def test_store_satisfies_graphstore_protocol() -> None:
    store = InMemoryGraphStore()
    assert isinstance(store, GraphStore)  # runtime_checkable structural conformance


def test_transaction_satisfies_protocol() -> None:
    store = InMemoryGraphStore()
    captured: dict[str, GraphTransaction] = {}
    with store.transaction(SYSTEM_TENANT, SYSTEM_PRINCIPAL) as txn:
        assert txn.tenant == SYSTEM_TENANT
        assert txn.principal == SYSTEM_PRINCIPAL
        txn.stage(sample_graph("a"))
        captured["txn"] = txn
    # A COMMITTED transaction satisfies the runtime-checkable Protocol. (We check
    # after commit because `isinstance` against a runtime_checkable Protocol
    # evaluates the `receipt` property, which — by contract — raises on an OPEN
    # transaction; on a committed one it safely returns the WriteReceipt.)
    assert isinstance(captured["txn"], GraphTransaction)
    assert isinstance(captured["txn"].receipt, WriteReceipt)
