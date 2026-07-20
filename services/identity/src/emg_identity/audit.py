"""Authentication event logging — temporary stand-in for the audit pipeline.

US-02 acceptance criterion: "failed authentication is logged via the audit
pipeline (FEAT-04-1)." FEAT-04-1 (Audit Event Pipeline, EPIC-04) is not
implemented until Sprint 5-6, so this module defines a small `AuditEventSink`
seam and a `StructuredLogAuditSink` implementation backed by
`emg_telemetry` (ADR-015's shared logging primitive, scaffolded Sprint 1).

This is a deliberate, documented interim measure, not a redefinition of
Module 6: every event emitted here already carries the actor/action/outcome/
correlation-id shape Module 6's append-only store will expect (ADR-015
Section 1), so swapping `StructuredLogAuditSink` for a real
`AuditPipelineSink` in EPIC-04 is a one-line dependency change in
`main.py` — no call site in this service needs to change.

Sprint 3 (FEAT-02-3) extends the Protocol with service-authentication
events, additively: every Sprint 2 method keeps its exact signature and
behavior. Note every method's parameters are safe, structured fields
(subject/client_id/reason strings) — there is no parameter anywhere in this
Protocol a caller could use to pass a raw secret or token, which is the
primary control behind "Secret redaction in logs" (Sprint 3 Required
Security Controls); redact.py is the backstop for free-text error messages
that reach `reason`.

Sprint 4 (FEAT-03-1/03-2) extends the Protocol again, additively, with
`record_authorization_decision` — US-03's "denial and allow decisions are
both logged" acceptance criterion. Every Sprint 2/3 method keeps its exact
signature and behavior.

Sprint 6 (FEAT-04-1) migrates the *wiring* to `PipelineAuditSink`
(`audit_pipeline.py`), which implements this same Protocol (Protocol-preserving
adapter): it emits the ADR-015 telemetry below AND durably forwards each event
to the Module 6 audit service. This module's Protocol and `StructuredLogAuditSink`
are unchanged — `StructuredLogAuditSink` is retained as the telemetry limb and
the degraded-mode / test fallback. No `record_*` signature changes.
"""

from __future__ import annotations

from typing import Protocol

from emg_auth_client import DecisionOutcome
from emg_telemetry import get_logger

_log = get_logger("identity")


class AuditEventSink(Protocol):
    def record_login_success(self, *, subject: str, correlation_id: str | None) -> None: ...

    def record_login_failure(
        self, *, username: str, reason: str, correlation_id: str | None
    ) -> None: ...

    def record_token_refresh_failure(self, *, reason: str, correlation_id: str | None) -> None: ...

    def record_service_auth_success(
        self, *, client_id: str, service_name: str, correlation_id: str | None
    ) -> None: ...

    def record_service_auth_failure(self, *, reason: str, correlation_id: str | None) -> None: ...

    def record_authorization_decision(
        self,
        *,
        subject: str,
        resource_type: str,
        action: str,
        outcome: DecisionOutcome,
        reason: str,
        correlation_id: str | None,
        policy_id: str | None = None,
    ) -> None: ...


class StructuredLogAuditSink:
    """Interim AuditEventSink backed by structured logging (ADR-015).

    Replace with a real Module 6-backed sink once FEAT-04-1 lands; the
    Protocol above is the contract that swap must satisfy.
    """

    def record_login_success(self, *, subject: str, correlation_id: str | None) -> None:
        _log.info(
            "login succeeded",
            extra={
                "actor": subject,
                "module": "identity",
                "action": "login",
                "outcome": "success",
            },
        )

    def record_login_failure(
        self, *, username: str, reason: str, correlation_id: str | None
    ) -> None:
        _log.warning(
            f"login failed: {reason}",
            extra={
                "actor": username,
                "module": "identity",
                "action": "login",
                "outcome": "denied",
            },
        )

    def record_token_refresh_failure(self, *, reason: str, correlation_id: str | None) -> None:
        _log.warning(
            f"token refresh failed: {reason}",
            extra={
                "actor": None,
                "module": "identity",
                "action": "token_refresh",
                "outcome": "denied",
            },
        )

    def record_service_auth_success(
        self, *, client_id: str, service_name: str, correlation_id: str | None
    ) -> None:
        _log.info(
            "service authentication succeeded",
            extra={
                "actor": client_id,
                "module": "identity",
                "action": "service_auth",
                "outcome": "success",
            },
        )

    def record_service_auth_failure(self, *, reason: str, correlation_id: str | None) -> None:
        _log.warning(
            f"service authentication failed: {reason}",
            extra={
                "actor": None,
                "module": "identity",
                "action": "service_auth",
                "outcome": "denied",
            },
        )

    def record_authorization_decision(
        self,
        *,
        subject: str,
        resource_type: str,
        action: str,
        outcome: DecisionOutcome,
        reason: str,
        correlation_id: str | None,
        policy_id: str | None = None,
    ) -> None:
        log_method = _log.info if outcome == "allow" else _log.warning
        extra = {
            "actor": subject,
            "module": "identity",
            "action": f"authorize:{resource_type}:{action}",
            "outcome": "success" if outcome == "allow" else "denied",
        }
        if policy_id:
            extra["policy_id"] = policy_id
        log_method(
            f"authorization {outcome}: {resource_type}/{action}: {reason}",
            extra=extra,
        )
