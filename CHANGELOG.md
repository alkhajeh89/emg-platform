# Changelog

All notable changes to the EMG™ Core Platform monorepo are documented here,
generated from Conventional Commits (`CONTRIBUTING.md`).

## [Unreleased]

### Sprint 2 — EPIC-02 Identity (FEAT-02-1, FEAT-02-2)

- `services/identity`: Keycloak-backed authentication (Direct Access Grants)
  against the local-dev realm seeded in
  `tools/seed-data/keycloak/emg-realm.json` (FEAT-02-1).
- `services/identity`: EMG-minted session issuance, refresh (with rotation),
  and expiry, independent of Keycloak's own token lifetimes; session claims
  carry `roles`/`attributes` matching `emg_auth_client.Principal` for
  Module 5's future PEP (FEAT-02-2).
- `SessionAuthClient`: concrete `emg_auth_client.AuthClient` implementation
  (Sprint 1 shipped the Protocol only).
- Interim authentication-event logging (`StructuredLogAuditSink`) standing
  in for the audit pipeline until FEAT-04-1 (Sprint 5-6).
- Wired `identity` into `docker-compose.yml` and a per-service CI workflow
  (`.github/workflows/service-identity.yml`) using the Sprint 1 reusable
  pipeline template.
- **Fix (libs/python/emg-telemetry):** `get_logger()`'s `extra=` handling
  crashed with `KeyError: Attempt to overwrite 'module' in LogRecord`
  whenever a caller passed the ADR-015 schema field `module` — a reserved
  `logging.LogRecord` attribute name. Discovered while wiring Sprint 2's
  audit logging (US-02's "failed authentication is logged" acceptance
  criterion depends on this). Fixed by namespacing the internal attribute
  names; the public `extra=` schema (`actor`, `module`, `action`, `outcome`)
  is unchanged. See `SPRINT-2-STATUS.md` for details.

### Sprint 1 — EPIC-01 Foundation (FEAT-01-1 through FEAT-01-4)

- Repository bootstrap: monorepo structure, branch protection, CODEOWNERS
  derived from ADR-016 (FEAT-01-1).
- Shared libraries scaffolding: common types, error handling, telemetry
  client, auth client interfaces, API client conventions (FEAT-01-2).
- Local development environment: containerized orchestration, seed data
  fixture scaffolding (FEAT-01-3).
- CI pipeline skeleton: staged pipeline template all services inherit
  (FEAT-01-4).
