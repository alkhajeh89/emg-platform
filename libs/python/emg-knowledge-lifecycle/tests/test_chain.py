"""VersionChain tests (FEAT-05-5): lineage helpers + structural rejections."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_knowledge_lifecycle import (
    InvalidChainError,
    KnowledgeVersion,
    VersionChain,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
MID = datetime(2026, 2, 1, tzinfo=timezone.utc)
META = VersionMetadata(created_at=T0, author="svc")


def _v(
    entity: str,
    n: int,
    state: VersionState,
    parent: VersionIdentifier | None = None,
    eff_from: datetime = T0,
    eff_to: datetime | None = None,
) -> KnowledgeVersion:
    return KnowledgeVersion(
        identifier=VersionIdentifier(entity_id=entity, version=n),
        state=state,
        metadata=META,
        parent=parent,
        effective_from=eff_from,
        effective_to=eff_to,
    )


def _linear_chain() -> VersionChain:
    v1 = _v("ent-a", 1, VersionState.SUPERSEDED, eff_from=T0, eff_to=MID)
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=v1.identifier, eff_from=MID)
    return VersionChain(versions=(v1, v2))


def test_chain_helpers() -> None:
    chain = _linear_chain()
    active = chain.active()
    assert active is not None and active.version == 2
    assert chain.latest().version == 2
    assert [v.version for v in chain.roots()] == [1]
    v1_id = VersionIdentifier(entity_id="ent-a", version=1)
    v2_id = VersionIdentifier(entity_id="ent-a", version=2)
    assert [v.version for v in chain.children(v1_id)] == [2]
    assert [v.version for v in chain.lineage(v2_id)] == [2, 1]
    assert chain.get(v1_id) is not None
    assert chain.get(VersionIdentifier(entity_id="ent-a", version=9)) is None


def test_chain_helpers_are_deterministic() -> None:
    chain = _linear_chain()
    assert chain.roots() == chain.roots()
    assert chain.lineage(VersionIdentifier(entity_id="ent-a", version=2)) == chain.lineage(
        VersionIdentifier(entity_id="ent-a", version=2)
    )


def test_empty_chain_rejected() -> None:
    with pytest.raises(InvalidChainError):
        VersionChain(versions=())


def test_mixed_entity_rejected() -> None:
    with pytest.raises(InvalidChainError):
        VersionChain(
            versions=(
                _v("ent-a", 1, VersionState.ACTIVE),
                _v("ent-b", 1, VersionState.PROPOSED),
            )
        )


def test_duplicate_identifier_rejected() -> None:
    with pytest.raises(InvalidChainError):
        VersionChain(
            versions=(
                _v("ent-a", 1, VersionState.SUPERSEDED, eff_from=T0, eff_to=MID),
                _v("ent-a", 1, VersionState.ACTIVE),
            )
        )


def test_orphaned_parent_rejected() -> None:
    v2 = _v(
        "ent-a",
        2,
        VersionState.ACTIVE,
        parent=VersionIdentifier(entity_id="ent-a", version=1),  # v1 not in chain
    )
    with pytest.raises(InvalidChainError):
        VersionChain(versions=(v2,))


def test_duplicate_active_rejected() -> None:
    v1 = _v("ent-a", 1, VersionState.ACTIVE, eff_from=T0, eff_to=MID)
    v2 = _v("ent-a", 2, VersionState.ACTIVE, parent=v1.identifier, eff_from=MID)
    with pytest.raises(InvalidChainError):
        VersionChain(versions=(v1, v2))


def test_cyclic_versions_are_rejected_when_building_a_chain() -> None:
    # A genuine cycle can only be assembled by bypassing per-version validation
    # (model_construct). Building a chain from such versions is rejected — pydantic
    # re-validates the items (per-version parent<child rule) before the chain's own
    # cycle detector even runs, so either a pydantic ValidationError or the chain's
    # InvalidChainError is acceptable; the point is the cycle never survives.
    from pydantic import ValidationError

    a = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=1),
        state=VersionState.PROPOSED,
        metadata=META,
        parent=VersionIdentifier(entity_id="ent-a", version=2),
        effective_from=T0,
        effective_to=None,
    )
    b = KnowledgeVersion.model_construct(
        identifier=VersionIdentifier(entity_id="ent-a", version=2),
        state=VersionState.PROPOSED,
        metadata=META,
        parent=VersionIdentifier(entity_id="ent-a", version=1),
        effective_from=T0,
        effective_to=None,
    )
    with pytest.raises((InvalidChainError, ValidationError)):
        VersionChain(versions=(a, b))


def test_single_version_chain_ok() -> None:
    chain = VersionChain(versions=(_v("ent-a", 1, VersionState.PROPOSED),))
    assert chain.active() is None
    assert chain.latest().version == 1


def test_chain_is_immutable() -> None:
    from pydantic import ValidationError

    chain = _linear_chain()
    with pytest.raises(ValidationError):
        chain.versions = ()


def test_lineage_unknown_identifier_raises_typed_not_found() -> None:
    # FIX 6: unknown-lineage lookup raises the typed emg_errors.NotFoundError,
    # not a bare KeyError.
    from emg_errors import NotFoundError

    chain = _linear_chain()
    with pytest.raises(NotFoundError):
        chain.lineage(VersionIdentifier(entity_id="ent-a", version=99))
