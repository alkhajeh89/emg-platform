from __future__ import annotations

import logging
from pathlib import Path

import pytest
from emg_audit_client import SubmittedAuditEvent
from emg_identity.audit import StructuredLogAuditSink
from emg_identity.audit_pipeline import (
    AuditDeliveryStatus,
    DurableSpool,
    PipelineAuditSink,
)


class _RecordingForwarder:
    """Forwarder that records delivered events."""

    def __init__(self) -> None:
        self.delivered: list[str] = []
        self.events: list[SubmittedAuditEvent] = []

    def deliver(self, event: SubmittedAuditEvent) -> None:
        self.events.append(event)
        self.delivered.append(event.event_id)


@pytest.fixture
def pipeline_sink(tmp_path: Path) -> tuple[PipelineAuditSink, _RecordingForwarder]:
    forwarder = _RecordingForwarder()
    sink = PipelineAuditSink(
        forwarder=forwarder,
        spool=DurableSpool(tmp_path / ".audit-spool"),
        status=AuditDeliveryStatus(),
        telemetry=StructuredLogAuditSink(),
        max_attempts=3,
        enabled=True,
    )
    return sink, forwarder


def test_structured_log_sink_logs_policy_id(caplog: pytest.LogCaptureFixture) -> None:
    sink = StructuredLogAuditSink()
    with caplog.at_level(logging.INFO, logger="emg.identity"):
        sink.record_authorization_decision(
            subject="u1",
            resource_type="res",
            action="act",
            outcome="allow",
            reason="matched",
            correlation_id="c1",
            policy_id="rule-123",
        )
    assert any(getattr(r, "policy_id", None) == "rule-123" for r in caplog.records)


def test_structured_log_sink_omits_policy_id_when_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = StructuredLogAuditSink()
    with caplog.at_level(logging.INFO, logger="emg.identity"):
        sink.record_authorization_decision(
            subject="u1",
            resource_type="res",
            action="act",
            outcome="allow",
            reason="matched",
            correlation_id="c1",
            policy_id=None,
        )
    # Assert that no log record has the policy_id field
    assert all(getattr(r, "policy_id", None) is None for r in caplog.records)


def test_pipeline_sink_delivers_policy_id_content(
    pipeline_sink: tuple[PipelineAuditSink, _RecordingForwarder],
) -> None:
    sink, forwarder = pipeline_sink
    sink.record_authorization_decision(
        subject="u1",
        resource_type="res",
        action="act",
        outcome="allow",
        reason="matched",
        correlation_id="c1",
        policy_id="rule-123",
    )
    assert len(forwarder.events) == 1
    assert forwarder.events[0].policy_id == "rule-123"


def test_pipeline_sink_omits_policy_id_content(tmp_path: Path) -> None:
    forwarder = _RecordingForwarder()
    sink = PipelineAuditSink(
        forwarder=forwarder,
        spool=DurableSpool(tmp_path / ".audit-spool"),
        status=AuditDeliveryStatus(),
        telemetry=StructuredLogAuditSink(),
        max_attempts=3,
        enabled=True,
    )
    sink.record_authorization_decision(
        subject="u1",
        resource_type="res",
        action="act",
        outcome="allow",
        reason="matched",
        correlation_id="c1",
        policy_id=None,
    )
    assert len(forwarder.events) == 1
    assert forwarder.events[0].policy_id is None
