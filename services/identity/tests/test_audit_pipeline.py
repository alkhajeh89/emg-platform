"""PipelineAuditSink degraded-mode behavior (Sprint 6, FEAT-04-1, Decision C)
and Protocol preservation.

Uses fake in-memory forwarders (no HTTP), so these tests are hermetic. They
prove: successful delivery, transient failure -> durable spool + retry ->
dead-letter, that ADR-015 telemetry keeps flowing, that the sink never raises
(so auth endpoints are never broken), and that PipelineAuditSink satisfies the
exact same AuditEventSink Protocol as StructuredLogAuditSink.
"""

from __future__ import annotations

import logging

from emg_audit_client import SubmittedAuditEvent
from emg_identity.audit import AuditEventSink, StructuredLogAuditSink
from emg_identity.audit_pipeline import (
    AuditDeliveryError,
    AuditDeliveryStatus,
    DurableSpool,
    PipelineAuditSink,
    bounded_backoff_delays,
)


class _RecordingForwarder:
    """Forwarder that records delivered events; optionally fails N times first
    (transient) to exercise the spool + retry path."""

    def __init__(self, *, fail_times: int = 0, permanent: bool = False) -> None:
        self.delivered: list[str] = []
        self._fail_times = fail_times
        self._permanent = permanent
        self.attempts = 0

    def deliver(self, event: SubmittedAuditEvent) -> None:
        self.attempts += 1
        if self._permanent:
            raise AuditDeliveryError("permanent reject", permanent=True)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise AuditDeliveryError("transient outage")
        self.delivered.append(event.event_id)


def _sink(tmp_path, forwarder, *, status=None) -> PipelineAuditSink:
    return PipelineAuditSink(
        forwarder=forwarder,
        spool=DurableSpool(tmp_path / ".audit-spool"),
        status=status or AuditDeliveryStatus(),
        telemetry=StructuredLogAuditSink(),
        max_attempts=3,
        enabled=True,
    )


def test_pipeline_sink_satisfies_the_audit_event_sink_protocol(tmp_path) -> None:
    """PipelineAuditSink implements every method of the AuditEventSink
    Protocol with a matching signature — verified structurally because the
    Protocol is intentionally not runtime_checkable (Sprint 2 code, unchanged).
    Both sinks expose exactly the same record_* surface."""
    import inspect

    sink = _sink(tmp_path, _RecordingForwarder())
    protocol_methods = [name for name in dir(AuditEventSink) if name.startswith("record_")]
    reference = StructuredLogAuditSink()
    assert protocol_methods  # sanity: the Protocol has record_* methods
    for name in protocol_methods:
        assert callable(getattr(sink, name))
        assert inspect.signature(getattr(sink, name)) == inspect.signature(getattr(reference, name))


def test_successful_delivery_forwards_event(tmp_path) -> None:
    forwarder = _RecordingForwarder()
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)
    sink.record_login_success(subject="dev.investigator", correlation_id="corr-1")
    assert len(forwarder.delivered) == 1
    assert status.snapshot()["degraded"] is False


def test_still_emits_adr015_telemetry_on_success(tmp_path, caplog) -> None:
    sink = _sink(tmp_path, _RecordingForwarder())
    with caplog.at_level(logging.INFO, logger="emg.identity"):
        sink.record_login_success(subject="dev.investigator", correlation_id="corr-1")
    assert any("login succeeded" in r.message for r in caplog.records)


def test_transient_failure_spools_durably_and_does_not_raise(tmp_path) -> None:
    forwarder = _RecordingForwarder(fail_times=5)
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)
    # Must not raise even though delivery fails.
    sink.record_login_failure(username="attacker", reason="bad password", correlation_id="c")
    snap = status.snapshot()
    assert snap["degraded"] is True
    assert snap["spooled_pending"] == 1
    assert (tmp_path / ".audit-spool").exists()


def test_spooled_event_is_replayed_when_service_recovers(tmp_path) -> None:
    forwarder = _RecordingForwarder(fail_times=1)
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)

    # First event fails delivery and is spooled.
    sink.record_login_success(subject="u1", correlation_id="c1")
    assert status.snapshot()["spooled_pending"] == 1

    # Service recovers; an explicit replay drains the spool.
    delivered, dead = sink.replay()
    assert delivered == 1
    assert dead == 0
    assert status.snapshot()["spooled_pending"] == 0
    assert status.snapshot()["degraded"] is False


def test_exhausted_retries_move_to_dead_letter(tmp_path) -> None:
    forwarder = _RecordingForwarder(fail_times=100)  # never recovers
    status = AuditDeliveryStatus()
    spool = DurableSpool(tmp_path / ".audit-spool")
    sink = PipelineAuditSink(
        forwarder=forwarder,
        spool=spool,
        status=status,
        telemetry=StructuredLogAuditSink(),
        max_attempts=2,
        enabled=True,
    )
    sink.record_login_success(subject="u1", correlation_id="c1")  # spooled (attempt 0)
    # Two replay passes exhaust max_attempts=2 -> dead-letter.
    sink.replay()
    delivered, dead = sink.replay()
    assert dead == 1
    assert status.snapshot()["dead_lettered"] == 1
    assert spool.pending_count() == 0


def test_permanent_rejection_is_dead_lettered_immediately(tmp_path) -> None:
    forwarder = _RecordingForwarder(permanent=True)
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)
    sink.record_login_success(subject="u1", correlation_id="c1")
    assert status.snapshot()["dead_lettered"] == 1
    assert status.snapshot()["last_outcome"] == "dead_letter"


def test_disabled_sink_emits_telemetry_only_and_never_spools(tmp_path, caplog) -> None:
    forwarder = _RecordingForwarder()
    sink = PipelineAuditSink(
        forwarder=forwarder,
        spool=DurableSpool(tmp_path / ".audit-spool"),
        status=AuditDeliveryStatus(),
        telemetry=StructuredLogAuditSink(),
        enabled=False,
    )
    with caplog.at_level(logging.INFO, logger="emg.identity"):
        sink.record_login_success(subject="u1", correlation_id="c1")
    assert any("login succeeded" in r.message for r in caplog.records)
    assert forwarder.delivered == []  # no forwarding
    assert not (tmp_path / ".audit-spool").exists()  # no spool side effect


def test_authorization_decision_maps_allow_to_success(tmp_path) -> None:
    forwarder = _RecordingForwarder()
    sink = _sink(tmp_path, forwarder)
    sink.record_authorization_decision(
        subject="dev.investigator",
        resource_type="identity.diagnostics",
        action="read",
        outcome="allow",
        reason="matched rule",
        correlation_id="c1",
    )
    assert len(forwarder.delivered) == 1


def test_bounded_backoff_delays_schedule() -> None:
    assert bounded_backoff_delays(max_attempts=4, base_seconds=0.5) == [0.5, 1.0, 2.0]
    assert bounded_backoff_delays(max_attempts=1, base_seconds=0.5) == []


# --- Priority 3: spool durability failure -> truthful CRITICAL, no false success


class _FailingSpool(DurableSpool):
    """A spool whose durable write always fails, to prove the sink escalates to
    CRITICAL and never claims the event was durably buffered."""

    def enqueue(self, event, *, attempts: int = 0) -> None:
        raise OSError("simulated spool write failure")


def test_spool_write_failure_escalates_to_critical_without_claiming_success(tmp_path) -> None:
    forwarder = _RecordingForwarder(fail_times=5)  # remote delivery also fails
    status = AuditDeliveryStatus()
    sink = PipelineAuditSink(
        forwarder=forwarder,
        spool=_FailingSpool(tmp_path / ".audit-spool"),
        status=status,
        telemetry=StructuredLogAuditSink(),
        enabled=True,
    )
    # Must not raise (auth endpoint stays available), but must NOT claim the
    # event was delivered or safely buffered.
    sink.record_login_success(subject="u1", correlation_id="c1")
    snap = status.snapshot()
    assert snap["critical"] is True
    assert snap["degraded"] is True
    assert snap["last_outcome"] == "critical"
    assert snap["last_outcome"] not in {"delivered", "spooled"}


def test_fsync_failure_is_treated_as_a_spool_failure(tmp_path, monkeypatch) -> None:
    """If flush succeeds but fsync fails, the write is not durable, so the sink
    must treat it as a spool failure (CRITICAL), never as success."""
    import os

    forwarder = _RecordingForwarder(fail_times=5)
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)

    def _boom(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", _boom)
    sink.record_login_success(subject="u1", correlation_id="c1")
    snap = status.snapshot()
    assert snap["critical"] is True
    assert snap["last_outcome"] == "critical"


def test_readiness_status_reflects_degraded_audit_delivery(tmp_path) -> None:
    """The AuditDeliveryStatus snapshot that the identity /readyz endpoint
    surfaces flips to degraded when events are only spooled, not delivered."""
    forwarder = _RecordingForwarder(fail_times=5)
    status = AuditDeliveryStatus()
    sink = _sink(tmp_path, forwarder, status=status)
    assert status.snapshot()["degraded"] is False
    sink.record_login_success(subject="u1", correlation_id="c1")
    assert status.snapshot()["degraded"] is True


def test_identity_readyz_endpoint_reports_degraded(tmp_path) -> None:
    """End-to-end: identity's additive /readyz maps a degraded audit-delivery
    status to an overall 'degraded' readiness (Decision C item 6)."""
    from emg_identity.dependencies import audit_delivery_status
    from emg_identity.main import create_app
    from fastapi.testclient import TestClient

    status = audit_delivery_status()  # process singleton the endpoint reads
    previous = status.snapshot()
    try:
        status._set(degraded=True, last_outcome="spooled", spooled_pending=1)
        client = TestClient(create_app())
        body = client.get("/readyz").json()
        assert body["status"] == "degraded"
        assert body["audit_delivery"]["degraded"] is True
    finally:
        # Restore the singleton so other tests are unaffected.
        status._set(
            degraded=previous["degraded"],
            last_outcome=previous["last_outcome"],
            spooled_pending=previous["spooled_pending"],
            critical=previous["critical"],
        )
