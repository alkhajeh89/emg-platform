"""Shared fixtures for the emg-knowledge-lifecycle test suite (FEAT-05-5)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_knowledge_lifecycle import (
    KnowledgeVersion,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)


@pytest.fixture
def t0() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def meta(t0: datetime) -> VersionMetadata:
    return VersionMetadata(created_at=t0, author="svc-ingest", note="initial")


def make_version(
    entity_id: str,
    version: int,
    state: VersionState,
    meta: VersionMetadata,
    *,
    parent: VersionIdentifier | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> KnowledgeVersion:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return KnowledgeVersion(
        identifier=VersionIdentifier(entity_id=entity_id, version=version),
        state=state,
        metadata=meta,
        parent=parent,
        effective_from=effective_from or base,
        effective_to=effective_to,
    )


@pytest.fixture
def two_version_chain_versions(
    meta: VersionMetadata, t0: datetime
) -> tuple[KnowledgeVersion, KnowledgeVersion]:
    """v1 SUPERSEDED (closed window) -> v2 ACTIVE (open window)."""
    mid = datetime(2026, 2, 1, tzinfo=timezone.utc)
    v1 = make_version(
        "ent-a", 1, VersionState.SUPERSEDED, meta, effective_from=t0, effective_to=mid
    )
    v2 = make_version(
        "ent-a", 2, VersionState.ACTIVE, meta, parent=v1.identifier, effective_from=mid
    )
    return v1, v2
