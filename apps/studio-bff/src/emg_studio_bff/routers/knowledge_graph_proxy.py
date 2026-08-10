"""Read-only forwarding routes to the Knowledge Graph Query API (ADR-036/042).

The generic proxy remains deliberately GET-only: it structurally cannot
reach any mutation route, regardless of what `path` names. ADR-042 adds one
separate POST transport mapped to one fixed read-only search endpoint; it is
not a generic POST proxy or mutation path. No SQL/Cypher construction, no
`emg_persistence`/`emg_memory_graph`/GraphStore import exists anywhere in
this module or application (ADR-036 D-10.2/D-10.3/D-10.6).

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

import json

import httpx
from emg_errors import AuthorizationError, UpstreamServiceError, ValidationError
from emg_telemetry import get_correlation_id
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from .. import delegation
from ..dependencies import CurrentSessionDep, SettingsDep, validate_csrf

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

_SEARCH_UPSTREAM_PATH = "/v1/knowledge-graph/search"
_SEARCH_RESPONSE_HEADERS = frozenset({"content-type"})


class GovernedSearchRequest(BaseModel):
    """Exact ADR-042 browser transport contract; no search semantics live here."""

    model_config = ConfigDict(extra="forbid")
    q: str
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


@router.post(
    "/search",
    summary="Governed enterprise entity search",
    description=(
        "Read-only search over POST for query confidentiality. Requires an authenticated "
        "Studio session and the existing double-submit CSRF cookie plus X-CSRF-Token header."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": GovernedSearchRequest.model_json_schema()}},
        }
    },
    responses={
        200: {"description": "Knowledge Graph governed-search response"},
        400: {"description": "Invalid bounded search transport"},
        401: {"description": "Missing session, invalid session, CSRF, or delegation failure"},
        502: {"description": "Knowledge Graph unavailable or returned an oversized response"},
    },
)
async def proxy_governed_search(
    request: Request, session: CurrentSessionDep, settings: SettingsDep
) -> Response:
    """Forward one validated body to one fixed read-only Knowledge Graph route."""
    validate_csrf(request, settings, session)
    if request.query_params:
        raise AuthorizationError("Search query parameters are not permitted")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise ValidationError("Invalid governed search request")
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError as exc:
        raise ValidationError("Invalid governed search request") from exc
    if content_length < 0 or content_length > settings.search_max_request_bytes:
        raise ValidationError("Invalid governed search request")
    body = await request.body()
    if not body or len(body) > settings.search_max_request_bytes:
        raise ValidationError("Invalid governed search request")
    try:
        decoded = json.loads(body, object_pairs_hook=_reject_duplicate_fields)
        GovernedSearchRequest.model_validate(decoded)
    except (UnicodeDecodeError, ValueError, PydanticValidationError) as exc:
        raise ValidationError("Invalid governed search request") from exc

    try:
        credential = await delegation.exchange_for_delegated_credential(
            settings,
            subject_token=session.access_token,
            audience=settings.knowledge_graph_audience,
        )
    except delegation.DelegationError as exc:
        raise AuthorizationError("Delegation failed") from exc

    upstream_url = f"{settings.knowledge_graph_base_url.rstrip('/')}{_SEARCH_UPSTREAM_PATH}"
    headers = {
        "Authorization": f"Bearer {credential.access_token}",
        "Content-Type": "application/json",
        "x-correlation-id": get_correlation_id() or "",
    }
    try:
        async with (
            httpx.AsyncClient(timeout=settings.search_upstream_timeout_seconds) as client,
            client.stream("POST", upstream_url, content=body, headers=headers) as upstream,
        ):
            response_body = bytearray()
            async for chunk in upstream.aiter_bytes():
                response_body.extend(chunk)
                if len(response_body) > settings.search_max_response_bytes:
                    raise UpstreamServiceError("Knowledge Graph response exceeded safe bound")
            status_code = upstream.status_code
            response_headers = dict(upstream.headers)
    except UpstreamServiceError:
        raise
    except httpx.HTTPError as exc:
        raise UpstreamServiceError("Knowledge Graph upstream request failed") from exc

    safe_headers = {
        key: value
        for key, value in response_headers.items()
        if key.lower() in _SEARCH_RESPONSE_HEADERS
    }
    return Response(
        content=bytes(response_body),
        status_code=status_code,
        headers=safe_headers,
        media_type=response_headers.get("content-type"),
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
