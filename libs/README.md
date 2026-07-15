# /libs — Shared Libraries (Module 3, ADR-012)

FEAT-01-2 — Shared Libraries Scaffolding. Empty, versioned packages every
downstream service (Modules 4-10) depends on from day one (Engineering
Master Plan §2). No business logic lives here — only cross-cutting
conventions: common types, error handling, telemetry, auth-client
interfaces, and API contract conventions.

| Package | Purpose |
| --- | --- |
| `python/emg-common-types` | Shared enums/value types used across services (e.g. Classification) |
| `python/emg-errors` | Base exception hierarchy and error-code conventions |
| `python/emg-telemetry` | Structured logging + correlation-ID propagation client (ADR-015) |
| `python/emg-auth-client` | Auth client interface/conventions (Module 4/5) — implemented against in EPIC-02/03 |
| `python/emg-api-contracts` | REST/GraphQL response envelope, pagination, and error-shape conventions (Enterprise API Architecture) |

Each package is independently versioned (semantic versioning, Engineering
Master Plan §17) so downstream teams are never blocked on a single shared
release (Engineering Backlog v1.0 §15, Risk 5).

TypeScript shared libraries for the presentation layer (ADR-014) are scoped
to EPIC-10 (Sprint 21+) and are not scaffolded this sprint, since frontend
implementation is explicitly out of Sprint 1 scope.
