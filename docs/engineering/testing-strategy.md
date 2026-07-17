# Testing Strategy

Reference: Engineering Master Plan §16.

Standard pyramid: unit tests for business logic, integration tests across
service boundaries, end-to-end tests for full user-journey scenarios —
layered with each module's own testing obligations as they are implemented
(Module 7 §26, Module 8's grounding validation tests, Module 9 §17's
AI/agentic threat cases, Module 10's Decision Replay reconstruction tests).

Sprint 1 status: `libs/python/*` packages carry unit tests
(`tests/test_import.py` per package) exercising the scaffolded shared-library
surface. `/services` test directories are scaffolded (`tests/.gitkeep`) with
no test suites yet, since no service has business logic this sprint.
Performance/load testing against ADR-017's compounded-load model begins once
a full request chain exists (EPIC-07 onward).

## Authorization testing harness (Sprint 5, FEAT-03-4)

`emg_policy_engine.testing` is the platform's shared, reusable toolkit for
authorization testing: `AuthorizationScenario` (a declarative
principal/resource/action/expected-outcome expectation), `assert_scenario`
(raises `AssertionError` on mismatch), and `run_scenarios` (batch runner
returning failure messages). Any service embedding the PEP
(`emg_policy_engine`) uses this to express positive/negative authorization
cases declaratively instead of hand-writing engine or HTTP assertions. It has
no pytest runtime dependency (plain `assert` / returned strings) and no
YAML/DSL layer. Reference adoption:
`services/identity/tests/test_authz_scenarios.py`, which runs the harness
against that service's real `config/policy.example.yaml`.

## Audit pipeline testing (Sprint 6, FEAT-04-1)

Audit tests are split across the libraries and the service, and run without
Docker or a database by default:

- `libs/python/emg-audit-pipeline/tests` — unit tests for canonical hashing,
  the append-only `InMemoryAuditEventStore` (sequence/chain assignment, US-04
  queries), event-id idempotency, hash-chain tamper detection, and
  pre-persistence validation/redaction.
- `services/audit/tests` — HTTP-level tests against the live service with an
  in-memory store and an injected local RSA keypair validator: authenticated
  ingest, schema rejection (422), sensitive-metadata rejection (400),
  duplicate idempotency, correlation propagation, redaction, integrity/tamper,
  and endpoint authorization (ingest vs. `svc-audit`-only read/integrity).
- `services/identity/tests/test_audit_pipeline.py` — the `PipelineAuditSink`
  degraded-mode behavior (Decision C): successful delivery, transient failure
  → durable spool → retry → dead-letter, continued ADR-015 telemetry, the
  never-raises guarantee, and Protocol preservation vs. `StructuredLogAuditSink`.
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres.py` —
  an **opt-in, skipped-by-default** suite (see its module docstring) that runs
  against a real Postgres from `docker-compose` to prove persistence, DB-layer
  append-only enforcement (INSERT/SELECT-only role denied UPDATE/DELETE),
  idempotency, and integrity.

## Provenance + chain-of-custody testing (Sprint 7, FEAT-04-2 + FEAT-04-3)

- `libs/python/emg-audit-pipeline/tests/test_backward_compat_hashing.py` — the
  **merge-blocking backward-compatibility gate**: the version-1 canonical
  payload is byte-for-byte identical to Sprint 6, a pinned literal golden
  version-1 hash still matches, a stored version-1 record re-verifies, and a
  mixed version-1/version-2 store verifies intact. If this fails, a change has
  silently altered the hash of already-published audit records.
- `libs/python/emg-audit-pipeline/tests/test_provenance.py` — provenance version
  stamping (server-derived), persistence, provenance tamper detection, and
  validation/redaction of oversized / secret-shaped provenance.
- `libs/python/emg-audit-pipeline/tests/test_custody_stores.py` — custody
  append-only, global + per-evidence sequencing, hash-chain links, queries,
  per-principal idempotency isolation, and the no-mutation/no-delete surface.
- `libs/python/emg-audit-pipeline/tests/test_custody_integrity.py` — custody
  mutation, deletion, non-increasing global sequence, per-evidence sequence gap,
  and schema-violating-row detection (each an explicit failure, never a raise).
- `services/audit/tests/test_provenance_api.py` — HTTP: provenance-carrying
  ingest persists a version-2 event, keeps the chain intact, and rejects
  oversized provenance (400).
- `services/audit/tests/test_custody_api.py` — HTTP: least-privilege
  (`svc-audit`-only) custody record/query/integrity, authorization negatives,
  idempotency, route-limit 422, invalid-action 422, and tamper detection.
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_custody.py`
  — an **opt-in, skipped-by-default** suite: custody persistence, DB-layer
  append-only enforcement, per-principal idempotency, integrity, a **25-thread
  concurrency** test (unique + contiguous global sequence, one valid chain), and
  the **FEAT-04-2 migration backward-compatibility** check (a version-1 and a
  version-2 event coexist and verify intact after `002` runs).

## Audit Query & Reporting Interface testing (Sprint 8, FEAT-04-4)

- `libs/python/emg-audit-pipeline/tests/test_pagination.py` — the cursor codec
  (`encode_cursor` / `decode_cursor` round-trip, opacity, and `CURSOR_INVALID`
  rejection of malformed / non-numeric / negative tokens), stable keyset
  pagination over the in-memory audit + custody stores (**every record exactly
  once, in order — no duplicates, no skips**, including when new rows are
  appended mid-walk), cursor+filter composition, and the new
  classification / module / action / outcome / source_system / has_provenance
  filters.
- `services/audit/tests/test_reporting_api.py` — HTTP: classification and
  richer-filter queries; `GET /audit/events/page` and
  `GET /audit/custody/events/page` cursor walks (no dupes / no skips, terminal
  cursor contract); JSON + CSV export for both surfaces (stable CSV header/
  column order, filtered export); `422` on invalid classification / export
  format, `400 CURSOR_INVALID` on a bad cursor; **least-privilege authorization**
  (the new page/export endpoints reject a non-`svc-audit` principal); backward
  compatibility (the Sprint 6 `GET /audit/events` still returns a list); and a
  **report-walk performance** test proving export issues one store query per
  page, never one per row (no N+1).
- `libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_reporting.py`
  — an **opt-in, skipped-by-default** suite: filters + keyset cursor pagination
  through real SQL (deterministic, no dupes / no skips), the `004` composite
  reporting indexes exist in `pg_indexes`, and — proving `004` is index-only /
  additive — existing rows and their hashes are untouched (integrity still
  intact after `004` runs).
- The **merge-blocking golden hash gate** (`test_backward_compat_hashing.py`,
  Sprint 7) continues to run unchanged: FEAT-04-4 adds only read paths and
  index-only SQL, so every stored `event_hash` is byte-for-byte unchanged.

## Core Ontology testing (Sprint 9, FEAT-05-1)

`libs/python/emg-ontology/tests` — pure, storage-independent unit tests (no
Docker, no database, no Neo4j; the ontology is a model + conformance library):

- `test_import.py` — version, pinned `ontology_schema_version`, public-surface
  export, and the registry counts (16 entity types, 8 relationship types).
- `test_core_envelope.py` — the governance envelope **required by
  construction**: missing classification / trust_score / provenance rejected at
  construction; trust-score range (boundary + out-of-range); frozen/immutable
  entities; extra-field (mass-assignment) rejection; invalid lifecycle state;
  effective-date validation; self-supersession rejection; and
  supersession-creates-a-new-version-while-the-original-stays-immutable.
- `test_domains.py` — every Organizational and Risk & Safety entity constructs
  with the envelope and pins its `entity_type`; a forged type tag is rejected; a
  missing envelope is non-conformant; archetype assignment is correct.
- `test_relationships.py` — the catalog contains exactly the approved eight
  types, each fully specified (source/target/cardinality/mutability/direction/
  self-loop); the `Relationship` model requires the envelope and is
  frozen/extra-forbidding.
- `test_conformance.py` — the US-05 "conformance test rejects a non-conforming
  write" criterion, one required rejection category per test: unknown entity/
  relationship type, missing classification/trust_score/provenance, out-of-range
  trust score, invalid lifecycle, invalid effective dates, mass-assignment,
  invalid source/target type, self-loop, dangling endpoint, classification
  dominance (edge below an endpoint), and cardinality — plus the accept paths
  and the typed-error raising helpers.
- `test_descriptor_golden.py` — the descriptor is deterministic (byte-stable)
  and its SHA-256 is pinned as a **merge-blocking golden gate**
  (`_GOLDEN_DESCRIPTOR_HASH`), the same pattern as the Module 6 golden audit
  hash; structural assertions confirm sorted output and the required-envelope
  flags on every entity.
- `test_audit_contract.py` — the graph-mutation action names and audit-module
  tag the future FEAT-05-2 write path will honor are pinned, and the metadata
  helper is proven to carry identifiers/types only (never entity content).

The Module 6 **golden audit-hash regression** and the full Sprint 1–8 suites run
unchanged alongside these; FEAT-05-1 is a new, isolated library and touches no
Module 1–6 code, record, or hash.
