# Audit Projector

Dedicated headless ADR-028 workload. It claims tenant-partitioned
`mutation_dispatch` rows on channel `audit`, projects immutable
`mutation_ledger.audit_intents`, and delivers through authenticated
`POST /audit/events` calls. It never writes the ledger or graph and never calls
HTTP inside a PostgreSQL transaction.

`EMG_AUDIT_PROJECTOR_TENANT_CREDENTIALS_JSON` is a secret JSON array:

```json
[
  {
    "tenant_id": "tenant-dev",
    "client_id": "emg-svc-audit-projector-tenant-dev",
    "client_secret": "provided-by-secret-store"
  }
]
```

Each tenant and client ID must be unique. The issued token must contain the
matching `tenant_id` and `azp`/`client_id`; mismatch fails closed. Production
requires HTTPS for Keycloak and Audit Service and TLS for PostgreSQL.

RC1 runs one replica. Retry is capped at eight attempts with deterministic
bounded jitter. Poison and exhausted rows remain durable and undelivered.
