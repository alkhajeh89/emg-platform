# Sprint 6 Design — EPIC-04 Audit Platform, FEAT-04-1 (Audit Event Pipeline)

Scope: **FEAT-04-1 only**, per `docs/architecture/EMG_Engineering_Backlog_v1.0.md`
§6 and US-04. FEAT-04-2 (Provenance Record Model), FEAT-04-3 (Digital Evidence
Chain-of-Custody), and FEAT-04-4 (full Audit Query & Reporting Interface) are
shifted to later Audit sprints and are **not** implemented here.

## US-04 traceability

> As a compliance officer, I want every governed action captured as an
> immutable audit event, so that any decision or access can be reconstructed
> later.

| Acceptance criterion | Where met |
| --- | --- |
| Audit events are append-only | `emg-audit-pipeline` stores expose only append/query; PostgreSQL app role has INSERT+SELECT only; no mutate API |
| Each event carries actor, action, timestamp, correlation identifier | `AuditEvent` required fields; server-assigned UTC `timestamp`; correlation id from `emg_telemetry` |
| Events queryable by actor, time range, correlation identifier | pipeline query API + `services/audit` `GET /audit/events` |
| No code path can delete or mutate a published event | no mutate methods (library + service); centralized hash chain makes out-of-band mutation detectable; DB grants (see the superuser caveat below) |

## Decision A (approved): hybrid — library-first core + minimal live service

- **`libs/python/emg-audit-client`** — the contract, analogous to
  `emg-auth-client` for Module 5: `AuditEvent`, `AuditSink` (Protocol:
  `record(event)`), `AuditEventStore` (Protocol), `AuditQuery`,
  `AuditOutcome`. No implementation, no I/O.
- **`libs/python/emg-audit-pipeline`** — the implementation, analogous to
  `emg-policy-engine`: canonical hashing, centralized hash chain + sequence
  assignment, `InMemoryAuditEventStore` (tests) and `PostgresAuditEventStore`
  (tier-1), integrity verification, idempotency, metadata/secret-key guards.
- **`services/audit`** — activated as a **minimal** live service that is a
  thin deployment shell over the libraries. It owns the single append-only
  store, ingestion, minimal US-04 query, integrity verification, and
  health/readiness reporting. It contains no audit business logic that is not
  in the libraries.

Rationale: the audit store is a shared system-of-record many services write
to and compliance queries; US-04 requires a real query surface; Master Plan §3
lists `audit` as a service tied to PostgreSQL; ADR-015 §Decision requires the
audit store be **distinct** from observability logs. Keeping all logic in
libraries preserves testability without a network and matches the Sprint 4/5
contract/implementation split.

## Decision B (approved): plain idempotent PostgreSQL init SQL

- PostgreSQL 16 (already in `docker-compose.yml`) is the tier-1 store.
- Schema is created by an **idempotent** SQL script in
  `tools/seed-data/postgres/` (mounted into the Postgres init dir). No Alembic
  this sprint; migration tooling is a documented later production-hardening
  item (`security-limitations.md`).
- Append-only application access is enforced by granting the application role
  **INSERT and SELECT only** — no application UPDATE or DELETE path exists.

## Decision C (approved with refinement): degraded-mode compatibility posture

Existing business actions (login/authentication) remain available during an
audit-service outage, but audit records are **never silently dropped**. The
`PipelineAuditSink` in `services/identity` behaves as follows:

1. Attempt delivery to the audit service.
2. On transient delivery failure, write the event to a **durable local
   spool**.
3. Retry with **bounded exponential backoff**.
4. Deliveries that exhaust retries move to an explicit **dead-letter** state
   for later replay.
5. Continue emitting the existing **ADR-015 structured telemetry** throughout
   degraded mode.
6. If neither remote durable acceptance nor local durable buffering succeeds:
   emit **critical degraded-state telemetry**, expose the degradation through
   health/readiness status, and **do not** claim the event was recorded.

Login/authentication endpoints do **not** fail solely because the remote audit
service is temporarily unavailable. This is the Sprint 6 compatibility posture
and a documented known limitation: higher-assurance ("no action without
audit", hard fail-closed) behavior for designated sensitive actions requires
security review and is a later-sprint decision.

## Centralized sequencing & hash chain (approved security requirement)

Sequence numbers and hash-chain links are assigned **inside `services/audit`
(the store)**, never by producer services. A producer (e.g. `services/identity`)
constructs an `AuditEvent` with its semantic fields and submits it; the store
assigns the authoritative `sequence_number`, `ingest_time`, `prev_hash`, and
`event_hash` under a single writer. This prevents independent producers from
constructing competing or forked chains. The `InMemoryAuditEventStore` and
`PostgresAuditEventStore` share the same centralized chaining logic from
`emg-audit-pipeline`.

## Data model (`AuditEvent`)

Server-assigned fields are set by the store at ingest; producer-supplied
fields describe the governed action.

| Field | Producer / Server | Notes |
| --- | --- | --- |
| `event_id` | producer | UUIDv4; **idempotency key** (duplicate submits are no-ops) |
| `sequence_number` | server | monotonic per store; ordering + gap detection |
| `timestamp` | server | **UTC, server-assigned authoritative** capture time |
| `ingest_time` | server | when the store accepted it (provenance) |
| `correlation_id` | producer | from `emg_telemetry.get_correlation_id()` |
| `actor` | producer | subject / client_id |
| `actor_type` | producer | `human` \| `service` |
| `module` | producer | emitting module, e.g. `identity` |
| `action` | producer | e.g. `login`, `authorize:identity.diagnostics:read` |
| `outcome` | producer | `success` \| `denied` \| `error` |
| `resource_type` / `resource_id` | producer | optional |
| `classification` | producer | `emg_common_types.Classification`, default `INTERNAL` |
| `source_system` / `source_component` | producer | provenance |
| `reason` | producer | safe free-text, redacted |
| `metadata` | producer | bounded dict; sensitive key names rejected |
| `prev_hash` / `event_hash` | server | SHA-256 canonical hash chain |

## Append-only & tamper-evidence

- **No mutation API** in either library or the service.
- **PostgreSQL**: application role granted INSERT + SELECT only.
- **Hash chain**: `event_hash = sha256(canonical(immutable_fields ‖ prev_hash))`.
  Integrity verification recomputes the chain and reports the first break, so
  **out-of-band** mutation (e.g. a direct DB write) is *detectable*.
- **Honest scope of the guarantee**: "no mutation or deletion" is an
  application-code and database-**role** guarantee. It is **not** an absolute
  claim that a PostgreSQL superuser (or someone with direct storage access)
  can never alter bytes; that residual risk is exactly what the hash-chain
  integrity verification exists to *detect*. This is documented as a known
  limitation.

## Security controls

- **No secrets/tokens** ever logged or stored: the semantic sink methods take
  only safe fields; `reason`/`metadata` pass a redaction + sensitive-key
  guard; raw access tokens, refresh tokens, client secrets, passwords, and
  Authorization headers are never accepted into an `AuditEvent`.
- **Metadata bound**: size-limited and key-name-validated before persistence.
- **Access control**: ingest requires a valid **service** token (Sprint 3
  `ServiceTokenValidator`); query/integrity are default-deny and restricted to
  appropriately authenticated existing service principals (including
  `svc-audit` where applicable). **No new roles are invented.** Human
  compliance-reporting access is part of the later full query/reporting
  feature (FEAT-04-4), not Sprint 6, beyond what US-04 explicitly requires.
- **Separation from telemetry**: `emg-telemetry` (observability logs) and the
  durable audit store remain distinct, per ADR-015.
- **UTC** server-assigned timestamps; **correlation ids** preserved
  end-to-end; **idempotent** ingestion by `event_id`.

## Migration from `StructuredLogAuditSink`

`services/identity` keeps its local `AuditEventSink` Protocol and every
`record_*` call site unchanged. A new `PipelineAuditSink` implements that same
Protocol (Protocol-preserving adapter), maps each semantic method to an
`AuditEvent`, forwards it to the audit service, and applies the Decision-C
degraded-mode behavior while still emitting ADR-015 telemetry.
`StructuredLogAuditSink` is retained as the fallback limb and test double. The
switch is a one-line change in `dependencies.py`.

## Explicit exclusions (this sprint)

- FEAT-04-2 (Provenance Record Model), FEAT-04-3 (Digital Evidence
  Chain-of-Custody), FEAT-04-4 (full Audit Query & Reporting Interface beyond
  US-04's minimal query).
- Message-queue/streaming ingestion, table partitioning, HA/multi-node store,
  retention purge jobs — later infra (EPIC-11/12).
- Human compliance-reporting UI/API surface (EPIC-10 / FEAT-04-4).
- Any Module 7–10 work; any new ADR; any new role; Sprint 7.
