# EMG v1 API cookbook

## Boundary and authentication

Browser code must use same-origin `/bff/*` only. It must not construct bearer, tenant, clearance,
or service identity headers. Backend examples below are for approved service/operator test clients
using a short-lived token from the configured identity system. Never place tokens in shell history,
URLs, documentation, or retained evidence.

OpenAPI documents are served by the FastAPI applications in environments where documentation is
enabled. Generated schemas are the field-level authority; this cookbook shows boundary-safe shapes,
not reusable credentials.

## Health

```bash
curl --fail --silent --show-error "${SERVICE_BASE_URL}/healthz"
curl --fail --silent --show-error "${SERVICE_BASE_URL}/readyz"
```

Do not treat liveness as dependency readiness.

## Studio session and logout

```text
GET  /bff/auth/login
GET  /bff/auth/session
POST /bff/auth/logout     Cookie: opaque session; X-CSRF-Token: readable CSRF value
```

The browser follows redirects for login. Logout requires both cookies according to the BFF’s
double-submit contract. No bearer token is exposed.

## Governed search through BFF

```bash
curl --fail --silent --show-error \
  -X POST "${STUDIO_ORIGIN}/bff/api/knowledge-graph/search" \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: ${CSRF_VALUE}" \
  -b "${OPAQUE_SESSION_COOKIE}" \
  --data '{"q":"approved search text","limit":20}'
```

For continuation, send the returned opaque cursor unchanged. Never decode, log, persist, place in a
URL, or combine it with a changed query. A rejected cursor requires a new search. Responses contain
visible results and continuation state, not totals or denied counts.

## Knowledge Graph service reads

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${SHORT_LIVED_TOKEN}" \
  "${KG_BASE_URL}/v1/knowledge-graph/entities/${ENCODED_ENTITY_ID}"

curl --fail --silent --show-error \
  -H "Authorization: Bearer ${SHORT_LIVED_TOKEN}" \
  "${KG_BASE_URL}/v1/knowledge-graph/entities/${ENCODED_ENTITY_ID}/neighbors"
```

The token—not a query parameter—determines tenant and clearance. Encode canonical IDs as path
segments. Follow only opaque continuation fields returned by the service.

## Audit service

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${SHORT_LIVED_SERVICE_TOKEN}" \
  "${AUDIT_BASE_URL}/audit/integrity"
```

Audit list/export routes are server-confined by tenant and classification. Never use client-side
filtering as a substitute. Event ingestion must use registered producer identity and canonical
schemas; consult generated OpenAPI rather than copying production event payloads into tickets.

## Expected errors

`401` means authentication/session failure; `403` means authorization/CSRF/claim denial; `409`
typically indicates governed conflict/idempotency/revision state; `422` means schema validation;
`503` means fail-closed dependency/readiness behavior. Clients must not reinterpret these as empty
authorized results. Preserve correlation IDs and sanitized response codes for support.
