# EMG v1 engineering handbook

## Repository model

- `apps/studio`: Next.js browser application.
- `apps/studio-bff`: mandatory same-origin session/delegation boundary.
- `services/identity`, `audit`, `audit-projector`, `knowledge-graph`: implemented runtimes.
- `libs/python`: governed domain, persistence, policy, contracts, telemetry, and support libraries.
- `infra`: provider-neutral manifests, overlays, provisioning and recovery contracts.
- `tools/ci`: fail-closed dependency, image, provisioning and release qualification.

Other service scaffolds and proposed capabilities are not v1 runtimes. The empty
`emg-entity-resolution` package is excluded from installation pending D-A-002.

## Architecture rules

PostgreSQL is authoritative; Neo4j is derived. Tenant, principal and clearance come from verified
credentials, never request fields. The service HTTP layer remains the PEP. Browsers call only BFF.
Delegated actions retain human and acting-service attribution. Audit and security failures fail
closed. Search returns no totals, facets, snippets, raw aliases, scores, or denied counts.

Accepted ADRs and the decision register are authoritative. Proposed ADRs and sprint plans do not
authorize implementation. ADR-037 is not implemented and must not be inferred from placeholder UI.

## Local workflow

Use Python 3.10, the hash-locked requirements, editable installers, and root npm lock. Canonical
gates are `make lint`, `make typecheck`, `make test`, Studio test/lint/typecheck/build/audit,
provisioning and manifest validators, security/supply-chain tests, pre-commit, and
`git diff --check`. External integration suites require explicit isolated test DSNs/URIs and must
never point at staging by accident.

## Change review checklist

- Architecture authority identified; no inferred feature scope.
- Trust boundary and tenant/classification behavior unchanged or explicitly reviewed.
- Startup validation rejects unsafe production configuration.
- Failure path is bounded and fail closed.
- Migrations are ordered, immutable, checksummed and compatible with rollout/rollback policy.
- Tests cover positive, negative, privilege, concurrency/idempotency and disclosure behavior.
- Dependency manifest and locks match imports/builds.
- Runtime image stays non-root, minimal, pinned, scanned, signed and attested.
- Documentation describes implemented behavior and marks live evidence `PENDING_LIVE`.

## Testing classification

Unit and mocked integration tests prove code contracts, not a deployed chain. Isolated PostgreSQL,
Neo4j, or Keycloak tests are real local integration but not staging. Only evidence bound to the
exact release and environment may be called live qualification. Skips must state the missing
environment variable or capability; xfail must not become a permanent release waiver.

## Release engineering

The tag workflow derives all eight governed images, builds once, runs the blocking vulnerability
policy, emits CycloneDX SBOMs, publishes immutable GHCR digests, signs with keyless OIDC, records
provenance, resolves bundles, and generates qualification/rollback evidence. A source or tooling
change requires a new candidate and fresh evidence. See the RC.9 preparation record.
