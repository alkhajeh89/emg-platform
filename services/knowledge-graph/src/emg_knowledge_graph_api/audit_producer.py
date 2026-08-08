"""Phase 2B — delegated-request audit attribution (ADR-038 §8.7 / AC-11).

Emits exactly one audit event for a delegated (human-attributed) request
that reaches a successful response, using the EXISTING, unmodified
`emg-audit-client` / audit-service ingest contract — the same contract the
ADR-038 capability verification already proved sufficient end-to-end
(`docs/security/adr-038/03_CAPABILITY_MATRIX.md`, property 10, and
`tests/security/adr_038/test_audit_attribution.py`). No new audit
mechanism, schema, or transport is introduced.

**Fail-closed (Phase 2B Required Change #2).** `emit_delegated_audit_event`
raises `UpstreamServiceError` on ANY failure — network, audit-service
outage, unexpected response — and callers (`routers/knowledge_graph.py`)
call this BEFORE returning their response, so a delegated request whose
audit attribution cannot be completed never reaches the caller as a 200.
This is a hard requirement specific to delegated requests: the pre-existing,
non-delegated service-to-service read path never calls this module at all
(see the `caller.acting_service is not None` gate at every call site) and
therefore has no new dependency on audit-service availability — its
behavior is byte-for-byte unchanged from before Phase 2B.

**Scope boundary (Finding 4): authentication failures are deliberately NOT
audit-attributed here.** A request whose token is missing, invalid, or
otherwise never resolves to a `CallerContext` at all (e.g.
`DelegatedCredentialValidator.validate()` itself raising) has no
authenticated identity to attribute to — ADR-038 §8.7's "every delegated
operation" presupposes a resolved delegated identity performing the
operation. Ordinary request/error logging (`emg_telemetry`, already wired
into every service's exception handler) remains the correct, unaffected
mechanism for auth-failure visibility; inventing an attribution record for
an unauthenticated caller would misrepresent who performed the (rejected)
operation, which is exactly what this contract must not do.

Producer identity: this service authenticates its OWN outbound call to the
audit service using its existing, already-registered
`emg-svc-knowledge-graph-writer` service credential (ADR-034) — an ordinary
service-to-service call, not part of the ADR-038 delegation chain itself.
`source_principal` on the resulting audit event is therefore server-assigned
by the audit service from THIS verified producer token (Sprint 6's existing
security guarantee — never client-supplied), landing as the Acting Service's
own identity; `actor`/`actor_type` carry the Human Principal, independently.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from emg_auth_client import Principal
from emg_errors import UpstreamServiceError
from emg_knowledge_graph import EdgeNotFoundError, EntityNotFoundError

from .authn import CallerContext
from .config import Settings


async def _fetch_producer_token(settings: Settings) -> str:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            settings.token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.audit_producer_client_id,
                "client_secret": settings.audit_producer_client_secret.get_secret_value(),
            },
        )
    if response.status_code != 200:
        raise UpstreamServiceError(
            f"failed to authenticate the audit producer credential: {response.status_code}"
        )
    body: dict[str, Any] = response.json()
    access_token = body["access_token"]
    assert isinstance(access_token, str)
    return access_token


async def emit_delegated_audit_event(
    settings: Settings,
    caller: CallerContext,
    *,
    resource_type: str,
    resource_id: str | None,
    action: str = "read",
    outcome: str = "success",
    correlation_id: str | None,
) -> None:
    """Raises `UpstreamServiceError` on any failure — see module docstring.
    No-op guard: callers are expected to check `caller.acting_service is not
    None` themselves (kept explicit at each call site rather than hidden
    here, so it stays visible exactly which routes emit audit events).

    `outcome` (correction-sprint Finding 6): `"success"` for a completed
    read, `"denied"` for an ADR-025 operation-level deny — `authorization.py`
    calls this with `outcome="denied"` before a delegated caller ever sees
    the resulting 403, so a denial is attributed too, not only successes.

    Type narrowing: `CallerContext.principal` is typed
    `ServicePrincipal | Principal`, but this function is only ever called
    when `caller.acting_service is not None`, which only
    `DelegatedCredentialValidator` sets — and that validator always
    constructs a `Principal` (human), never a `ServicePrincipal`. The
    `isinstance` check below makes that invariant explicit (mirrors the
    identical precedent in `dependencies.py::mutation_principal_ref_dependency`)
    rather than leaving `.subject` access unprovable to the type checker."""
    assert (
        caller.acting_service is not None
    ), "emit_delegated_audit_event called for a non-delegated caller"
    if not isinstance(caller.principal, Principal):
        raise UpstreamServiceError(
            "delegated audit attribution requires a human Principal, got a ServicePrincipal — "
            "this should be unreachable; DelegatedCredentialValidator always constructs a Principal"
        )

    event: dict[str, Any] = {
        "event_id": f"kg-delegated-{uuid.uuid4()}",
        "actor": caller.principal.subject,
        "actor_type": "human",
        "module": "knowledge-graph",
        "action": action,
        "outcome": outcome,
        "correlation_id": correlation_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "classification": caller.principal.attributes.get(
            "classification_clearance", "UNCLASSIFIED"
        ),
        "source_system": "knowledge-graph",
        "metadata": {
            "acting_service": caller.acting_service,
            "tenant_id": caller.tenant.value,
        },
    }

    try:
        producer_token = await _fetch_producer_token(settings)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.audit_service_base_url}/audit/events",
                json=event,
                headers={
                    "Authorization": f"Bearer {producer_token}",
                    # Final correction-sprint Finding 7: the correlation id
                    # was already correct in the persisted event body (read
                    # by audit's own event-schema mapping), but the audit
                    # SERVICE's own HTTP-level correlation_id_middleware
                    # reads the *header*, independently of the body — without
                    # this, audit's own request logs for this ingest call
                    # carried a different, freshly-generated id than the
                    # rest of the Browser->BFF->KG chain.
                    "x-correlation-id": correlation_id or "",
                },
            )
    except httpx.HTTPError as exc:
        raise UpstreamServiceError(f"audit event submission failed: {exc}") from exc

    if response.status_code != 200:
        raise UpstreamServiceError(f"audit service rejected the event: {response.status_code}")


@dataclass
class _DelegatedAuditOutcome:
    """Mutable outcome tracker a route body can adjust (e.g. to `"denied"`)
    before the `delegated_audit` context manager below emits its exit-time
    audit event."""

    outcome: str = "success"


@asynccontextmanager
async def delegated_audit(
    settings: Settings,
    caller: CallerContext,
    *,
    resource_type: str,
    resource_id: str | None,
    action: str = "read",
    correlation_id: str | None,
) -> AsyncIterator[_DelegatedAuditOutcome | None]:
    """Final correction-sprint Finding 4 — complete ADR-038 §8.7 audit
    attribution for every delegated outcome, not only success.

    A no-op for non-delegated callers (`caller.acting_service is None`) —
    yields `None`, emits nothing, exactly today's behavior, unaffected.

    For a delegated caller, wraps a route body and emits exactly ONE audit
    event on exit, regardless of how the body completed:

    - normal return, tracker.outcome left at its default -> `"success"`.
    - the route explicitly sets `tracker.outcome = "denied"` before raising
      its classification-driven not-found exception (ADR-026's uniform
      denial: the HTTP response stays indistinguishable from a genuine
      not-found, but the *audit record* — a separate, internal governance
      trail — correctly distinguishes the two, per Finding 4).
    - `EntityNotFoundError`/`EdgeNotFoundError` propagating WITHOUT the
      route having set `"denied"` first -> `"not_found"` (genuine absence,
      raised by the application layer itself, before any classification
      gating ran).
    - any other exception -> `"error"`.

    RBAC-level `"denied"` (an ADR-025 operation-level deny) is NOT this
    context manager's concern — `authorization.py`'s
    `require_permission_delegated_aware` already audit-attributes that case
    on its own, at the dependency layer, before the route body (and this
    context manager) ever runs. This avoids double-auditing that case.

    Fail-closed, uniformly: if the audit emission itself fails, this raises
    `UpstreamServiceError`, which SUPERSEDES whatever was propagating (a
    normal return, a 404-shaped not-found/denied exception, or an original
    unrelated error) — an unattributed delegated outcome, of any kind, is
    never an acceptable fallback (ADR-038 §8.7 / Required Change #2,
    extended by Finding 4 to cover every outcome, not only success)."""
    if caller.acting_service is None:
        yield None
        return

    tracker = _DelegatedAuditOutcome()
    try:
        yield tracker
    except (EntityNotFoundError, EdgeNotFoundError):
        if tracker.outcome == "success":
            tracker.outcome = "not_found"
        raise
    except Exception:
        tracker.outcome = "error"
        raise
    finally:
        await emit_delegated_audit_event(
            settings,
            caller,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            outcome=tracker.outcome,
            correlation_id=correlation_id,
        )
