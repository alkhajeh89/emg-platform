# Security Decision Register

| Decision Area | Current Evidence | Status | Required Decision |
| :--- | :--- | :--- | :--- |
| Identity Provider | Keycloak (`docker-compose.yml`) | Implemented | Keycloak is integrated for identity management |
| M2M Authentication | OAuth 2.0 Client Credentials (`services/identity/`) | Implemented | OAuth 2.0 Client Credentials used for M2M authentication |
| Authorization PEP/ABAC | `libs/python/emg-auth-client/` | Implemented | Library-based PEP with ABAC engine |
| RBAC Role Catalog | `libs/python/emg-policy-engine/` | Implemented | Baseline RBAC role catalog used for policy evaluation |
| Audit Storage | Postgres (`services/audit/`) | Implemented | Postgres used for append-only audit record storage |
| Agent Security | None | TBD | TBD — requires engineering or architecture decision |
| Data Protection | None | TBD | TBD — requires engineering or architecture decision |
| Threat Model | None | TBD | TBD — requires engineering or architecture decision |
| Compliance | None | TBD | TBD — requires engineering or architecture decision |
