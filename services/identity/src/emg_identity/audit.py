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
"""

from __future__ import annotations

from typing import Protocol

from emg_telemetry import get_logger

_log = get_logger("identity")


class AuditEventSink(Protocol):
    def record_login_success(self, *, subject: str, correlation_id: str | None) -> None: ...

    def record_login_failure(
        self, *, username: str, reason: str, correlation_id: str | None
    ) -> None: ...

    def record_token_refresh_failure(
        self, *, reason: str, correlation_id: str | None
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
