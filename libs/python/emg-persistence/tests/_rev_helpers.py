"""Constructors for revision-repository tests."""

from __future__ import annotations

from datetime import datetime, timezone

from emg_persistence.revisions import Revision
from emg_platform_core import PrincipalRef, TenantId

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
TENANT = TenantId.of("acme")
PRINCIPAL = PrincipalRef.service("ingest")


def _hash(seed: str) -> str:
    """A deterministic 64-char lowercase hex string for tests."""
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def make_revision(
    revision_number: int,
    *,
    tenant: TenantId = TENANT,
    content_seed: str | None = None,
    parent_hash: str | None = None,
    node_count: int = 1,
    edge_count: int = 0,
) -> Revision:
    seed = content_seed if content_seed is not None else f"{tenant.value}:{revision_number}"
    return Revision(
        tenant=tenant,
        revision_number=revision_number,
        content_hash=_hash(seed),
        parent_hash=parent_hash,
        principal=PRINCIPAL,
        node_count=node_count,
        edge_count=edge_count,
        graph_json={"nodes": [], "edges": []},
        created_at=_T0,
    )
