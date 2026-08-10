# EMG Studio BFF

Phase 2B (ADR-035, ADR-036, ADR-038): the mandatory Backend-for-Frontend. The
only trusted browser-application boundary — terminates OIDC Authorization
Code + PKCE S256 for human sessions, holds a server-side session, and
performs OAuth 2.0 Token Exchange (RFC 8693) to obtain audience-scoped
Delegated Credentials for downstream Platform Services.

Not a Policy Enforcement Point (ADR-036 D-4); holds no direct datastore
access (ADR-036 D-10); constructs no trusted identity from browser-supplied
input (ADR-038 §9.9).

See `docs/security/adr-038/` for the full governing architecture, capability
verification, and production configuration record.

## Governed enterprise search

ADR-042 adds one dedicated browser-facing route:

```text
POST /api/knowledge-graph/search
  -> POST {knowledge_graph_base_url}/v1/knowledge-graph/search
```

This is a read-only search operation transported as POST so the query never
appears in a URL. It requires the existing authenticated Studio session and
double-submit CSRF cookie/header pair. The BFF performs a fresh RFC 8693
exchange for the configured Knowledge Graph audience on every request and
forwards only the resulting delegated bearer credential. Browser cookies,
authorization, CSRF, tenant, clearance, principal, Acting Service, and other
identity headers are never forwarded.

The request schema is limited to `q`, optional `limit`, and optional `cursor`.
The original validated JSON body is forwarded without semantic rewriting.
Requests are limited to 8 KiB. Responses are streamed into a bounded 4 MiB
buffer, derived from the 100-item maximum page and canonical EntitySummary
string bounds. Search upstream calls have an explicit 10-second default
timeout, no automatic retry, and fail closed on exchange, transport, timeout,
or size-limit failure. These settings are configurable only within hard
startup-validated maxima.

Raw/normalized query text, cursors, request bodies, result bodies, and tokens
must never be written to logs, traces, telemetry, errors, correlation metadata,
redirects, or cookies. The existing generic proxy remains GET-only; there is
no generic browser-controlled POST path or target.

## Running locally

```bash
cd apps/studio-bff
uvicorn emg_studio_bff.main:app --port 8010 --reload
```

## Testing

```bash
pytest apps/studio-bff/tests -v
```
