"""LifecycleEvent tests (FEAT-05-5): only legal transitions are representable."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from emg_knowledge_lifecycle import LifecycleEvent, VersionIdentifier, VersionState
from pydantic import ValidationError

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
VID = VersionIdentifier(entity_id="ent-a", version=1)


def test_legal_event_constructs() -> None:
    ev = LifecycleEvent(
        version=VID,
        from_state=VersionState.ACTIVE,
        to_state=VersionState.SUPERSEDED,
        occurred_at=T0,
        actor="svc",
    )
    assert ev.from_state is VersionState.ACTIVE
    assert not ev.is_restore


def test_illegal_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LifecycleEvent(
            version=VID,
            from_state=VersionState.ACTIVE,
            to_state=VersionState.ARCHIVED,  # not a legal transition
            occurred_at=T0,
            actor="svc",
        )


def test_self_transition_event_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LifecycleEvent(
            version=VID,
            from_state=VersionState.ACTIVE,
            to_state=VersionState.ACTIVE,
            occurred_at=T0,
            actor="svc",
        )


def test_restore_event_flagged() -> None:
    ev = LifecycleEvent(
        version=VID,
        from_state=VersionState.ARCHIVED,
        to_state=VersionState.SUPERSEDED,
        occurred_at=T0,
        actor="svc",
    )
    assert ev.is_restore


def test_event_is_immutable() -> None:
    ev = LifecycleEvent(
        version=VID,
        from_state=VersionState.PROPOSED,
        to_state=VersionState.ACTIVE,
        occurred_at=T0,
        actor="svc",
    )
    with pytest.raises(ValidationError):
        ev.actor = "other"
