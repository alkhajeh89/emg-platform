from __future__ import annotations

from collections.abc import Callable

import pytest
from emg_audit_client import SubmittedAuditEvent

MakeSubmitted = Callable[..., SubmittedAuditEvent]


def _make_submitted(
    event_id: str = "evt-1",
    *,
    actor: str = "dev.investigator",
    actor_type: str = "human",
    action: str = "login",
    outcome: str = "success",
    correlation_id: str | None = "corr-1",
    reason: str = "",
    metadata: dict[str, str] | None = None,
) -> SubmittedAuditEvent:
    return SubmittedAuditEvent(
        event_id=event_id,
        actor=actor,
        actor_type=actor_type,  # type: ignore[arg-type]
        module="identity",
        action=action,
        outcome=outcome,  # type: ignore[arg-type]
        correlation_id=correlation_id,
        source_system="identity",
        reason=reason,
        metadata=metadata or {},
    )


@pytest.fixture
def make_submitted() -> MakeSubmitted:
    """Factory fixture returning a builder for SubmittedAuditEvent test data."""
    return _make_submitted
