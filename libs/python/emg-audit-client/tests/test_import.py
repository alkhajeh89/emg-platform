from __future__ import annotations

import pytest
from emg_audit_client import (
    AuditEvent,
    AuditQuery,
    SubmittedAuditEvent,
    __version__,
)
from emg_common_types import Classification
from pydantic import ValidationError


def test_version() -> None:
    # Sprint 6 shipped 0.1.0; Sprint 7 bumped to 0.2.0 (provenance + custody);
    # Sprint 8 (FEAT-04-4) bumps to 0.3.0 (richer query + cursor pagination).
    # (This assertion was stale at 0.1.0 on the merged mainline — corrected as a
    # documented pre-condition before FEAT-04-4, see SPRINT-8-STATUS.md.)
    assert __version__ == "0.3.0"


def test_submitted_event_minimal_construction() -> None:
    event = SubmittedAuditEvent(
        event_id="evt-1",
        actor="dev.investigator",
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        source_system="identity",
    )
    assert event.classification is Classification.INTERNAL
    assert event.metadata == {}
    assert event.correlation_id is None


def test_submitted_event_is_frozen() -> None:
    event = SubmittedAuditEvent(
        event_id="evt-1",
        actor="a",
        actor_type="service",
        module="identity",
        action="service_auth",
        outcome="success",
        source_system="identity",
    )
    with pytest.raises(ValidationError):
        event.actor = "b"  # type: ignore[misc]


def test_submitted_event_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        SubmittedAuditEvent(
            event_id="evt-1",
            actor="a",
            actor_type="human",
            module="identity",
            action="login",
            outcome="success",
            source_system="identity",
            authorization="Bearer secret",  # type: ignore[call-arg]
        )


def test_submitted_event_rejects_invalid_outcome() -> None:
    with pytest.raises(ValidationError):
        SubmittedAuditEvent(
            event_id="evt-1",
            actor="a",
            actor_type="human",
            module="identity",
            action="login",
            outcome="maybe",  # type: ignore[arg-type]
            source_system="identity",
        )


def test_audit_event_is_frozen() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    event = AuditEvent(
        event_id="evt-1",
        # source_principal became a required, server-assigned field in the
        # Sprint 6 P5 idempotency fix; this construction was stale without it on
        # the merged mainline — corrected as a documented pre-condition before
        # FEAT-04-4 (see SPRINT-8-STATUS.md).
        source_principal="svc-test",
        sequence_number=1,
        timestamp=now,
        ingest_time=now,
        prev_hash="",
        event_hash="abc",
        actor="a",
        actor_type="human",
        module="identity",
        action="login",
        outcome="success",
        source_system="identity",
    )
    with pytest.raises(ValidationError):
        event.event_hash = "tampered"  # type: ignore[misc]


def test_query_limit_bounds() -> None:
    assert AuditQuery().limit == 100
    with pytest.raises(ValidationError):
        AuditQuery(limit=0)
    with pytest.raises(ValidationError):
        AuditQuery(limit=10_000)
