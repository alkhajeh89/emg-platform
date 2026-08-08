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

## Running locally

```bash
cd apps/studio-bff
uvicorn emg_studio_bff.main:app --port 8010 --reload
```

## Testing

```bash
pytest apps/studio-bff/tests -v
```
