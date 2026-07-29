# EMG Operations Security Guide

## Operational gates

Deploy only images and third-party services pinned by immutable digest. Confirm
the deployed digest matches the release provenance subject. Treat a failed
startup configuration gate as a deployment failure; do not bypass it.

Monitor HTTP 413 and 503 rates, authentication throttling, audit export volume,
database pool saturation, policy denials, readiness degradation, and container
resource pressure. Correlation identifiers are limited to 128 conservative
ASCII characters; invalid inbound values are replaced so they cannot amplify
or forge structured logs.

Audit exports are capped at 100,000 rows and streamed page-by-page. Increase
that ceiling only through a reviewed release with memory/load evidence.

## Incident handling

Revoke exposed credentials, rotate dependent credentials, preserve the
append-only audit and mutation ledgers, and redeploy from a verified immutable
artifact. Never place tokens, DSNs, credentials, request bodies, or raw
customer records in tickets or logs.
