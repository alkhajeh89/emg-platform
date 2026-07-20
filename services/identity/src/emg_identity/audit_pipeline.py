"""Sprint 6 (FEAT-04-1): forward identity audit events to the Module 6 audit
service, with the Decision-C degraded-mode compatibility posture.

`PipelineAuditSink` implements the existing `AuditEventSink` Protocol
(audit.py) — every `record_*` method keeps its exact signature, so no call
site in `routers/` changes. Each method does two things additively:

1. emits the existing ADR-015 structured telemetry via a wrapped
   `StructuredLogAuditSink` (unchanged observable behavior, and the
   degraded-mode floor), and
2. forwards a durable `AuditEvent` to the audit service.

Decision C behavior for the forward limb (never raises, so login/auth
endpoints never fail merely because the audit service is unavailable):

1. attempt delivery to the audit service;
2. on transient failure, write the event to a durable local spool;
3. retry with bounded exponential backoff (via `replay`);
4. exhausted deliveries move to an explicit dead-letter file for replay;
5. ADR-015 telemetry keeps being emitted throughout;
6. if neither remote delivery nor durable spooling succeeds, emit CRITICAL
   degraded-state telemetry and mark the process degraded (surfaced by the
   readiness endpoint) — never silently claim the event was recorded.

`emg-telemetry` (observability logs) and the durable audit store stay
distinct, per ADR-015.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from emg_audit_client import AuditOutcome, SubmittedAuditEvent
from emg_auth_client import DecisionOutcome
from emg_telemetry import get_correlation_id, get_logger

from .audit import StructuredLogAuditSink

_log = get_logger("identity")

_SERVICE_NAME = "identity"


class AuditDeliveryError(Exception):
    """Raised by a forwarder when delivery to the audit service fails. A
    `permanent=True` error (e.g. a validation/authorization rejection) is
    dead-lettered immediately rather than retried."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class AuditForwarder(Protocol):
    def deliver(self, event: SubmittedAuditEvent) -> None:
        """Deliver one event to the audit service. Raise `AuditDeliveryError`
        on failure (the sink decides spool vs dead-letter)."""
        ...


@dataclass
class AuditDeliveryStatus:
    """Process-level audit-delivery health, surfaced by the readiness
    endpoint. `degraded` is True whenever events are not being durably
    accepted remotely."""

    degraded: bool = False
    last_outcome: str = "idle"
    spooled_pending: int = 0
    dead_lettered: int = 0
    critical: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "degraded": self.degraded,
                "last_outcome": self.last_outcome,
                "spooled_pending": self.spooled_pending,
                "dead_lettered": self.dead_lettered,
                "critical": self.critical,
            }

    def _set(self, **kwargs: object) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)


class DurableSpool:
    """A minimal durable, file-backed spool + dead-letter store (JSONL).

    Not a production message queue — it is the Sprint 6 durability floor so an
    event is never silently dropped when the audit service is briefly
    unavailable. A real queue is later infrastructure (documented limitation).
    """

    def __init__(self, spool_path: Path) -> None:
        self._spool_path = spool_path
        self._dead_letter_path = spool_path.with_suffix(".dead-letter")
        self._lock = threading.Lock()
        self._spool_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _append_line_durably(path: Path, line: str) -> None:
        """Append one line and make it durable: write, flush, and fsync the
        file descriptor. Raises if ANY step fails, so a caller can never treat
        a partially-completed (non-durable) write as success (Sprint 6
        security-review fix, Priority 3)."""
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def enqueue(self, event: SubmittedAuditEvent, *, attempts: int = 0) -> None:
        """Durably spool an event. Raises on any write/flush/fsync failure —
        the caller (PipelineAuditSink) treats a raise as 'not durably buffered'
        and escalates to CRITICAL rather than claiming the event was recorded."""
        line = json.dumps({"attempts": attempts, "event": event.model_dump(mode="json")})
        with self._lock:
            self._append_line_durably(self._spool_path, line)

    def _read_all(self) -> list[dict[str, object]]:
        if not self._spool_path.exists():
            return []
        with self._spool_path.open("r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def _rewrite(self, records: list[dict[str, object]]) -> None:
        tmp = self._spool_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self._spool_path)

    def dead_letter(self, record: dict[str, object]) -> None:
        with self._lock:
            self._append_line_durably(self._dead_letter_path, json.dumps(record))

    def pending_count(self) -> int:
        with self._lock:
            return len(self._read_all())

    def dead_letter_count(self) -> int:
        if not self._dead_letter_path.exists():
            return 0
        with self._lock, self._dead_letter_path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())

    def drain(self, forwarder: AuditForwarder, *, max_attempts: int) -> tuple[int, int]:
        """Attempt to redeliver every spooled event. Returns
        (delivered, dead_lettered). Events that exhaust `max_attempts` are
        moved to the dead-letter file."""
        with self._lock:
            records = self._read_all()
            remaining: list[dict[str, object]] = []
            delivered = 0
            dead = 0
            for record in records:
                event = SubmittedAuditEvent.model_validate(record["event"])
                attempts = int(cast(int, record.get("attempts", 0))) + 1
                try:
                    forwarder.deliver(event)
                    delivered += 1
                except AuditDeliveryError as exc:
                    if exc.permanent or attempts >= max_attempts:
                        self._dead_letter_locked({"attempts": attempts, "event": record["event"]})
                        dead += 1
                    else:
                        remaining.append({"attempts": attempts, "event": record["event"]})
            self._rewrite(remaining)
            return delivered, dead

    def _dead_letter_locked(self, record: dict[str, object]) -> None:
        # Already holding self._lock (called from drain()); write durably.
        self._append_line_durably(self._dead_letter_path, json.dumps(record))


class PipelineAuditSink:
    """AuditEventSink that emits ADR-015 telemetry and forwards durable audit
    events to the audit service (Sprint 6). Protocol-preserving: implements
    the same `AuditEventSink` Protocol as `StructuredLogAuditSink`."""

    def __init__(
        self,
        *,
        forwarder: AuditForwarder,
        spool: DurableSpool,
        status: AuditDeliveryStatus,
        telemetry: StructuredLogAuditSink | None = None,
        max_attempts: int = 5,
        enabled: bool = True,
    ) -> None:
        self._forwarder = forwarder
        self._spool = spool
        self._status = status
        self._telemetry = telemetry or StructuredLogAuditSink()
        self._max_attempts = max_attempts
        # When disabled, the sink emits ADR-015 telemetry only and does not
        # forward or spool — byte-for-byte the Sprint 2-5 StructuredLogAuditSink
        # observable behavior. Forwarding is enabled by configuration once the
        # audit service is present (Sprint 6 compatibility posture).
        self._enabled = enabled

    # --- AuditEventSink Protocol (identical signatures to audit.py) --------

    def record_login_success(self, *, subject: str, correlation_id: str | None) -> None:
        self._telemetry.record_login_success(subject=subject, correlation_id=correlation_id)
        self._record(
            actor=subject,
            actor_type="human",
            action="login",
            outcome="success",
            correlation_id=correlation_id,
        )

    def record_login_failure(
        self, *, username: str, reason: str, correlation_id: str | None
    ) -> None:
        self._telemetry.record_login_failure(
            username=username, reason=reason, correlation_id=correlation_id
        )
        self._record(
            actor=username,
            actor_type="human",
            action="login",
            outcome="denied",
            reason=reason,
            correlation_id=correlation_id,
        )

    def record_token_refresh_failure(self, *, reason: str, correlation_id: str | None) -> None:
        self._telemetry.record_token_refresh_failure(reason=reason, correlation_id=correlation_id)
        self._record(
            actor="anonymous",
            actor_type="human",
            action="token_refresh",
            outcome="denied",
            reason=reason,
            correlation_id=correlation_id,
        )

    def record_service_auth_success(
        self, *, client_id: str, service_name: str, correlation_id: str | None
    ) -> None:
        self._telemetry.record_service_auth_success(
            client_id=client_id, service_name=service_name, correlation_id=correlation_id
        )
        self._record(
            actor=client_id,
            actor_type="service",
            action="service_auth",
            outcome="success",
            correlation_id=correlation_id,
        )

    def record_service_auth_failure(self, *, reason: str, correlation_id: str | None) -> None:
        self._telemetry.record_service_auth_failure(reason=reason, correlation_id=correlation_id)
        self._record(
            actor="anonymous",
            actor_type="service",
            action="service_auth",
            outcome="denied",
            reason=reason,
            correlation_id=correlation_id,
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
        self._telemetry.record_authorization_decision(
            subject=subject,
            resource_type=resource_type,
            action=action,
            outcome=outcome,
            reason=reason,
            correlation_id=correlation_id,
            policy_id=policy_id,
        )
        self._record(
            actor=subject,
            actor_type="human",
            action=f"authorize:{resource_type}:{action}",
            outcome="success" if outcome == "allow" else "denied",
            resource_type=resource_type,
            reason=reason,
            correlation_id=correlation_id,
            policy_id=policy_id,
        )

    # --- durable forwarding (Decision C) -----------------------------------

    def _record(
        self,
        *,
        actor: str,
        actor_type: str,
        action: str,
        outcome: AuditOutcome,
        correlation_id: str | None,
        resource_type: str | None = None,
        reason: str = "",
        policy_id: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        submitted = SubmittedAuditEvent(
            event_id=str(uuid.uuid4()),
            actor=actor,
            actor_type=actor_type,  # type: ignore[arg-type]
            module="identity",
            action=action,
            outcome=outcome,
            correlation_id=correlation_id or get_correlation_id(),
            resource_type=resource_type,
            source_system=_SERVICE_NAME,
            reason=reason,
            policy_id=policy_id,
        )
        self._deliver(submitted)

    def _deliver(self, submitted: SubmittedAuditEvent) -> None:
        """Never raises: a failure here must not break the calling auth
        endpoint (Decision C)."""
        try:
            self._forwarder.deliver(submitted)
        except AuditDeliveryError as exc:
            self._handle_delivery_failure(submitted, exc)
            return
        except Exception as exc:  # unexpected forwarder error -> treat as transient
            self._handle_delivery_failure(submitted, AuditDeliveryError(str(exc)))
            return
        # Delivered. Opportunistically drain any previously-spooled events.
        self._status._set(last_outcome="delivered", degraded=False, critical=False)
        self._try_drain()

    def _handle_delivery_failure(
        self, submitted: SubmittedAuditEvent, exc: AuditDeliveryError
    ) -> None:
        if exc.permanent:
            try:
                self._spool.dead_letter(
                    {"attempts": self._max_attempts, "event": submitted.model_dump(mode="json")}
                )
                self._status._set(
                    last_outcome="dead_letter",
                    degraded=True,
                    dead_lettered=self._spool.dead_letter_count(),
                )
            except Exception:
                self._emit_critical(submitted)
            return
        try:
            self._spool.enqueue(submitted)
            self._status._set(
                last_outcome="spooled",
                degraded=True,
                spooled_pending=self._spool.pending_count(),
            )
            _log.warning(
                f"audit delivery degraded; event spooled durably: {exc}",
                extra={
                    "actor": submitted.actor,
                    "module": "identity",
                    "action": "audit_forward",
                    "outcome": "degraded",
                },
            )
        except Exception:
            self._emit_critical(submitted)

    def _emit_critical(self, submitted: SubmittedAuditEvent) -> None:
        self._status._set(last_outcome="critical", degraded=True, critical=True)
        _log.critical(
            "AUDIT DELIVERY CRITICAL: could not deliver or durably spool an audit event; "
            "event is NOT confirmed recorded",
            extra={
                "actor": submitted.actor,
                "module": "identity",
                "action": "audit_forward",
                "outcome": "critical",
            },
        )

    def _try_drain(self) -> None:
        try:
            if self._spool.pending_count() == 0:
                return
            _, dead = self._spool.drain(self._forwarder, max_attempts=self._max_attempts)
            pending = self._spool.pending_count()
            self._status._set(
                spooled_pending=pending,
                dead_lettered=self._spool.dead_letter_count(),
                degraded=pending > 0,
            )
            if dead:
                _log.warning(
                    f"audit spool moved {dead} event(s) to dead-letter after exhausting retries",
                    extra={
                        "actor": "anonymous",
                        "module": "identity",
                        "action": "audit_replay",
                        "outcome": "dead_letter",
                    },
                )
        except Exception:  # pragma: no cover - defensive; draining must never break a request
            pass

    def replay(self) -> tuple[int, int]:
        """Explicitly attempt to redeliver spooled events. Returns
        (delivered, dead_lettered)."""
        delivered, dead = self._spool.drain(self._forwarder, max_attempts=self._max_attempts)
        pending = self._spool.pending_count()
        self._status._set(
            spooled_pending=pending,
            dead_lettered=self._spool.dead_letter_count(),
            degraded=pending > 0,
        )
        return delivered, dead


class HttpAuditForwarder:
    """Default forwarder: POSTs an audit event to the audit service's
    `/audit/events` ingest endpoint over HTTP, authenticated with a service
    token from an injected `token_provider`.

    Response mapping: 2xx succeeds; 400/401/403/422 are permanent (validation
    or authorization) and dead-lettered immediately; everything else
    (5xx, timeouts, connection errors, token-acquisition failures) is transient
    and spooled for retry.
    """

    _PERMANENT_STATUSES = frozenset({400, 401, 403, 422})

    def __init__(
        self,
        *,
        base_url: str,
        token_provider: TokenProvider,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/audit/events"
        self._token_provider = token_provider
        self._timeout = timeout_seconds

    def deliver(self, event: SubmittedAuditEvent) -> None:
        import httpx

        try:
            token = self._token_provider()
        except Exception as exc:  # token acquisition failure -> transient
            raise AuditDeliveryError(f"could not obtain service token: {exc}") from exc

        headers = {"Authorization": f"Bearer {token}"}
        correlation_id = event.correlation_id or get_correlation_id()
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id
        try:
            response = httpx.post(
                self._url,
                json=event.model_dump(mode="json"),
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise AuditDeliveryError(f"audit service unreachable: {exc}") from exc

        if response.status_code // 100 == 2:
            return
        permanent = response.status_code in self._PERMANENT_STATUSES
        raise AuditDeliveryError(
            f"audit service rejected event: HTTP {response.status_code}",
            permanent=permanent,
        )


class TokenProvider(Protocol):
    def __call__(self) -> str: ...


def bounded_backoff_delays(*, max_attempts: int, base_seconds: float) -> list[float]:
    """Deterministic bounded exponential backoff schedule (no jitter, so it is
    testable): base, 2*base, 4*base, ... for `max_attempts - 1` retries."""
    return [base_seconds * (2**i) for i in range(max(max_attempts - 1, 0))]


def sleep_backoff(delays: list[float]) -> None:  # pragma: no cover - timing wrapper
    for delay in delays:
        time.sleep(delay)
