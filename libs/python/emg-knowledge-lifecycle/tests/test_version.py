"""Version-model tests (FEAT-05-5): identifier, metadata, KnowledgeVersion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from emg_knowledge_lifecycle import (
    KnowledgeVersion,
    VersionIdentifier,
    VersionMetadata,
    VersionState,
)
from emg_knowledge_lifecycle.limits import MAX_VERSION_NUMBER
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _meta() -> VersionMetadata:
    return VersionMetadata(created_at=T0, author="svc")


def test_identifier_key_and_sort_key() -> None:
    vid = VersionIdentifier(entity_id="ent-a", version=3)
    assert vid.key == "ent-a@3"
    assert vid.sort_key == ("ent-a", 3)


def test_identifier_rejects_bad_version() -> None:
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id="ent-a", version=0)
    with pytest.raises(ValidationError):
        VersionIdentifier(entity_id="ent-a", version=MAX_VERSION_NUMBER + 1)


def test_identifier_is_immutable_and_hashable() -> None:
    vid = VersionIdentifier(entity_id="ent-a", version=1)
    with pytest.raises(ValidationError):
        vid.version = 2
    assert vid == VersionIdentifier(entity_id="ent-a", version=1)


def test_metadata_optional_note_and_immutable() -> None:
    m = VersionMetadata(created_at=T0, author="svc")
    assert m.note is None
    with pytest.raises(ValidationError):
        m.author = "other"


def test_version_construction_and_helpers() -> None:
    v = KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="ent-a", version=2),
        state=VersionState.ACTIVE,
        metadata=_meta(),
        parent=VersionIdentifier(entity_id="ent-a", version=1),
        effective_from=T0,
    )
    assert v.entity_id == "ent-a"
    assert v.version == 2
    assert v.is_effective_at(T0 + timedelta(days=5))
    assert not v.is_effective_at(T0 - timedelta(days=1))


def test_version_is_immutable() -> None:
    v = KnowledgeVersion(
        identifier=VersionIdentifier(entity_id="ent-a", version=1),
        state=VersionState.PROPOSED,
        metadata=_meta(),
        effective_from=T0,
    )
    with pytest.raises(ValidationError):
        v.state = VersionState.ACTIVE


def test_version_rejects_self_parent() -> None:
    with pytest.raises(ValidationError):
        KnowledgeVersion(
            identifier=VersionIdentifier(entity_id="ent-a", version=1),
            state=VersionState.ACTIVE,
            metadata=_meta(),
            parent=VersionIdentifier(entity_id="ent-a", version=1),
            effective_from=T0,
        )


def test_version_rejects_cross_entity_parent() -> None:
    with pytest.raises(ValidationError):
        KnowledgeVersion(
            identifier=VersionIdentifier(entity_id="ent-a", version=2),
            state=VersionState.ACTIVE,
            metadata=_meta(),
            parent=VersionIdentifier(entity_id="ent-b", version=1),
            effective_from=T0,
        )


def test_version_rejects_non_decreasing_parent() -> None:
    with pytest.raises(ValidationError):
        KnowledgeVersion(
            identifier=VersionIdentifier(entity_id="ent-a", version=2),
            state=VersionState.ACTIVE,
            metadata=_meta(),
            parent=VersionIdentifier(entity_id="ent-a", version=2),
            effective_from=T0,
        )
    with pytest.raises(ValidationError):
        KnowledgeVersion(
            identifier=VersionIdentifier(entity_id="ent-a", version=2),
            state=VersionState.ACTIVE,
            metadata=_meta(),
            parent=VersionIdentifier(entity_id="ent-a", version=3),
            effective_from=T0,
        )


def test_version_rejects_invalid_effective_window() -> None:
    with pytest.raises(ValidationError):
        KnowledgeVersion(
            identifier=VersionIdentifier(entity_id="ent-a", version=1),
            state=VersionState.ACTIVE,
            metadata=_meta(),
            effective_from=T0,
            effective_to=T0,  # not strictly after
        )
