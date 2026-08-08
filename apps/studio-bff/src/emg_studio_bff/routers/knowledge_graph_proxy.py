"""Read-only forwarding proxy to the Knowledge Graph Query API (ADR-036).

Deliberately GET-only: this router structurally cannot reach any mutation
route, regardless of what `path` names — "no new mutation routes" is
enforced by the proxy's own shape, not merely by omission. No SQL/Cypher
construction, no `emg_persistence`/`emg_memory_graph`/GraphStore import
anywhere in this module or this application (ADR-036 D-10.2/D-10.3/D-10.6
— see `tests/test_dependency_boundary.py`).

Every call performs a fresh RFC 8693 token exchange (`delegation.py`) — no
caching (Phase 2B Required Change #4) — then forwards the request verbatim
to Knowledge Graph, attaching the resulting Delegated Credential. The BFF
does not re-derive, merge, enrich, or re-rank the response (ADR-036 D-6):
Knowledge Graph's own status code and JSON body are returned unchanged.
Knowledge Graph's own ADR-025 403 / ADR-026 classification-denial (404 /
pruned-list / `found=false` / empty-item) shapes therefore reach the
browser exactly as Knowledge Graph produced them.
"""

from __future__ import annotations

import httpx
from emg_errors import AuthorizationError, UpstreamServiceError
from emg_telemetry import get_correlation_id
from fastapi import APIRouter, Request, Response

from .. import delegation
from ..dependencies import CurrentSessionDep, SettingsDep

router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])

# Response headers that would leak internal service topology or duplicate
# this application's own framing — never forwarded to the browser (ADR-036:
# "do not expose internal service topology to the browser unnecessarily").
#
# `set-cookie` (final correction-sprint Finding 9): a downstream service
# must never be able to inject a cookie into the browser's trusted BFF
# origin. Knowledge Graph does not set cookies today, but this proxy's own
# behavior — not downstream trust — is what ADR-036 D-10 requires; stripping
# it here means no future proxied service, misconfigured or compromised,
# could ever smuggle a cookie (including one colliding with the session/CSRF
# cookie names) into a context the browser treats as first-party.
_STRIPPED_UPSTREAM_HEADERS = frozenset(
    {
        "server",
        "date",
        "content-length",
        "content-encoding",
        "connection",
        "cache-control",
        "set-cookie",
    }
)

# Correction-sprint Finding 10 (ADR-036 D-5): "A BFF route that accepts a
# tenant identifier from the browser — as parameter, path segment, body
# field, header, or cookie — is a defect." This proxy forwards
# `request.query_params` to Knowledge Graph; any of these names is rejected
# outright rather than silently stripped, so a client attempting this is
# told clearly rather than having it silently no-op.
_REJECTED_QUERY_PARAMS = frozenset(
    {
        "tenant_id",
        "tenant",
        "classification_clearance",
        "clearance",
        "principal",
        "subject",
        "acting_service",
    }
)


@router.get("/{path:path}")
async def proxy_read(
    path: str, request: Request, session: CurrentSessionDep, settings: SettingsDep
) -> Response:
    rejected = _REJECTED_QUERY_PARAMS.intersection(request.query_params.keys())
    if rejected:
        raise AuthorizationError(
            f"client-supplied security-identity query parameter(s) are not permitted: "
            f"{sorted(rejected)}"
        )

    try:
        credential = await delegation.exchange_for_delegated_credential(
            settings,
            subject_token=session.access_token,
            audience=settings.knowledge_graph_audience,
        )
    except delegation.DelegationError as exc:
        # ADR-038 §9.10 Invariant — Fail Closed: an exchange failure is
        # never treated as "proceed without a Delegated Credential" or
        # "fall back to a service-only identity". The request simply fails.
        raise AuthorizationError(f"delegation failed: {exc}") from exc

    upstream_url = f"{settings.knowledge_graph_base_url}/{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            upstream_response = await client.get(
                upstream_url,
                params=request.query_params,
                headers={
                    "Authorization": f"Bearer {credential.access_token}",
                    # This BFF's own correlation-id middleware (main.py) has
                    # already established one id for the whole request — use
                    # THAT, not a raw re-read of the (often absent/browser-
                    # controlled) incoming header (correction-sprint Finding 9,
                    # the KG-side correlation fix is Finding 7).
                    "x-correlation-id": get_correlation_id() or "",
                },
            )
        except httpx.HTTPError as exc:
            raise UpstreamServiceError(f"knowledge-graph upstream request failed: {exc}") from exc

    headers = {
        k: v
        for k, v in upstream_response.headers.items()
        if k.lower() not in _STRIPPED_UPSTREAM_HEADERS
    }
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=headers,
        media_type=upstream_response.headers.get("content-type"),
    )
