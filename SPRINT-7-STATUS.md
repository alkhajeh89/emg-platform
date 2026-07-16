# Sprint 7 Completion Status — EPIC-04 Audit Completion (FEAT-04-2 + FEAT-04-3)

**Status:** Sprint 7 — **Complete — pending merge.** Approved controlled
split: **FEAT-04-2 (Provenance Record Model)** and **FEAT-04-3 (Digital Evidence
Chain-of-Custody)** implemented; **FEAT-04-4 (Audit Query & Reporting Interface)
explicitly deferred** to the immediate next sprint. **EPIC-04 remains incomplete
until FEAT-04-4 is delivered**, and EPIC-05 (Module 7) is blocked until then.
Nothing committed, pushed, or merged.

**Security review result:** a final security-focused review of the Sprint 7
working-tree diff concluded **APPROVE** — no blocking defects, no high-risk
findings, no scope violations. See §8 for the full disposition summary.

**Branch:** `feature/sprint-7-audit-completion` (verified; based on `develop`
after the Sprint 6 merge, PR #6 `1fe6bc7`).

**Repository:** `/Users/mak/Documents/GitHub/emg-platform`.

**Scope discipline:** engineering sequencing only — no Architecture Baseline
change, no Module 6 redesign, **no new ADR**, **no new role**. Module 6 is
formally "Audit, Provenance & Digital Evidence" (ADR-015; ADR-016 §1 row 3), so
provenance and chain-of-custody are already inside frozen scope.

**DoD note:** this change touches provenance and audit behavior, so per Master
Plan §15 / Backlog §14 it requires a formal organizational **Security
Reviewer sign-off** before merge, in addition to the security-focused review
recorded above. No such external, organizational sign-off is claimed here —
the APPROVE outcome above was produced as an engineering review within this
session, not by the organization's designated Security Reviewer role, and
does not substitute for it.

## 1. Acceptance-Criteria Verification

Feature-level criteria (proposed at grooming from the §3 Feature descriptions +
Module 6). US-04 (FEAT-04-1) remains met and unchanged.

**FEAT-04-2 — Provenance Record Model**

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 2.1 | Provenance captures source system/component, originating actor + principal, correlation id, event-time vs. ingest-time, classification | Done | `ProvenanceRecord` (`emg_audit_client/provenance.py`); `test_provenance.py` |
| 2.2 | Transformation history + parent/source refs + evidence origin/collection method | Done | `TransformationStep`, `EventRef`; `test_event_with_provenance_is_version_2_and_persists_provenance` |
| 2.3 | Provenance is schema-versioned; event self-identifies version 1/2 | Done | `schema_version` server-assigned; `test_schema_version_is_server_assigned_from_presence_of_provenance` |
| 2.4 | Provenance is in the hash for v2 events; tampering detected | Done | version-aware `canonical_payload`; `test_provenance_is_part_of_the_hash_tamper_detected` |
| 2.5 | Malformed/oversized/secret provenance rejected/redacted before persistence | Done | `validate_and_sanitize_provenance`; `test_oversized_*`, `test_secret_shaped_provenance_free_text_is_redacted` |
| 2.6 | Every Sprint 6 (v1) record remains readable and re-verifies to its stored hash | Done | **golden test** (`test_backward_compat_hashing.py`); opt-in migration test |

**FEAT-04-3 — Digital Evidence Chain-of-Custody**

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 3.1 | Custody record: evidence id, custodian + prior, action, server UTC transfer time, reason | Done | `CustodyEvent` (`custody.py`); `test_custody_stores.py` |
| 3.2 | Append-only; per-evidence custody sequence + global chain sequence | Done | stores expose only append/query/verify; `003_evidence_custody.sql` INSERT/SELECT-only; `test_per_evidence_custody_sequence_is_independent`, `test_global_chain_sequence_is_monotonic_and_links` |
| 3.3 | Tamper detection via hash chain | Done | `verify_custody_chain`; `test_mutation_is_detected` |
| 3.4 | Gap detection (missing per-evidence sequence) | Done | `test_per_evidence_sequence_gap_is_detected` |
| 3.5 | Duplicate handling scoped to `(source_principal, custody_event_id)` | Done | `test_append_is_idempotent_by_principal_and_custody_event_id`, `test_different_principals_same_custody_event_id_are_distinct` |
| 3.6 | Existing roles only (`svc-audit`); no new role | Done | `require_audit_custodian`; `test_record_custody_denied_for_non_audit_principal` |
| 3.7 | Integrity never raises on a malformed row (explicit failure result) | Done | defensive `verify_integrity`; `test_schema_violating_row_is_reported_not_raised` |

EPIC-04 exit criterion (Backlog §6 "Complete audit and provenance"): **partially
met** — provenance and chain-of-custody complete; the query/reporting interface
(FEAT-04-4) is the remaining piece, deferred by approval. EPIC-04 is **not**
closed this sprint.

## 2. Architecture Traceability

| Requirement source | Where implemented |
| --- | --- |
| Backlog §3 FEAT-04-2 "Source/actor/timestamp/method tracking" | `ProvenanceRecord` on `AuditEvent`; hashed for v2; persisted (`002_audit_provenance.sql`) |
| Backlog §3 FEAT-04-3 "Evidence integrity and custody tracking" | `custody.py` models + `custody_store.py` (in-memory + Postgres) + `services/audit` custody router + `003_evidence_custody.sql` |
| Module 6 "Audit, Provenance & Digital Evidence"; ADR-016 §1 (CISO/CDO owner; Audit Platform Team steward) | Extends the Sprint 6 hybrid; no new service, no new ADR |
| ADR-015 §Decision (audit store distinct from telemetry) | Custody ledger + provenance stay in the audit store; `emg_telemetry` untouched |
| Master Plan §15 / Backlog §14 (security-reviewer sign-off for audit/provenance) | Flagged (§Status, §10) |
| Backlog §7 / Master Plan §17 (EPIC-05 depends on EPIC-04 complete) | EPIC-05 explicitly kept blocked until FEAT-04-4 lands |

## 3. Golden v1 Compatibility Evidence (backward compatibility)

- **Version-aware canonicalization** (`hashing.py`): a schema-version-1 event's
  canonical payload is **byte-for-byte identical** to Sprint 6 (no
  `schema_version`/`provenance` keys); version-2 adds them.
- `test_backward_compat_hashing.py` (**merge-blocking gate**, 6 tests, all
  green):
  - `test_v1_canonical_payload_is_byte_identical_to_sprint6` — payload string
    equals the exact Sprint 6 key set.
  - `test_v1_golden_hash_is_unchanged` — a pinned literal golden hash
    (`8c38a4a4…dbce25d`) still matches.
  - `test_default_schema_version_is_v1_backward_compatible` — a Sprint 6-style
    call (no `schema_version` arg) yields the v1 payload.
  - `test_v1_record_reverifies_under_v7_code`, `test_mixed_v1_v2_chain_verifies_intact`.
- **No published record is rewritten, re-hashed, migrated, or mutated.**
  `002_audit_provenance.sql` only ADDs a defaulted `schema_version` and a
  nullable `provenance` column; `001_audit_events.sql` is unchanged.

## 4. Provenance Integrity Evidence

- Provenance is part of the v2 canonical hash; mutating any provenance field on
  a stored record breaks integrity (`test_provenance_is_part_of_the_hash_tamper_detected`,
  `first_broken_sequence` reported).
- Oversized transformation history / parent refs / free-text values are rejected
  (`AUDIT_PROVENANCE_*` error codes); secret-shaped free text is redacted.
- Ingest path enforces it end-to-end: `test_ingest_rejects_oversized_provenance`
  → HTTP 400 `AUDIT_PROVENANCE_VALUE_TOO_LONG`;
  `test_ingest_with_provenance_persists_version_2` → stored `schema_version == 2`.

## 5. Custody Append-Only & Tamper/Gap Evidence

- **Append-only**: `InMemoryCustodyEventStore` / `PostgresCustodyEventStore`
  expose only `append`/`query`/`verify_integrity`
  (`test_store_has_no_mutation_or_delete_api`); the Postgres role has
  INSERT/SELECT only (`003_evidence_custody.sql`; opt-in
  `test_custody_application_role_cannot_update_or_delete`).
- **Single-writer chain**: global `chain_sequence` + per-evidence
  `custody_sequence` assigned centrally; producers cannot supply chain state
  (`test_source_principal_is_not_producer_supplied`). Postgres serializes via a
  dedicated advisory lock (`0x43555354` "CUST", distinct from the audit chain's
  `0x41554449` "AUDI").
- **Tamper/deletion/gap/invalid-schema** all detected as explicit failures, never
  a raise (`test_custody_integrity.py`): mutation, deleted-middle, non-increasing
  global sequence, per-evidence sequence gap, unparseable row.
- **HTTP**: least-privilege `svc-audit`-only record/query/integrity; idempotency;
  route-limit 422; invalid-action 422; tamper detected via
  `GET /audit/custody/integrity` (`test_custody_api.py`).

## 6. Database Migration Evidence

- **`002_audit_provenance.sql`** — idempotent `ADD COLUMN IF NOT EXISTS
  schema_version INTEGER NOT NULL DEFAULT 1` + `ADD COLUMN IF NOT EXISTS
  provenance JSONB` + supporting indexes. Additive only; existing rows get
  `schema_version = 1`, `provenance = NULL`, hashes untouched.
- **`003_evidence_custody.sql`** — idempotent `CREATE TABLE IF NOT EXISTS
  evidence_custody_events` with `PRIMARY KEY (source_principal,
  custody_event_id)`, `UNIQUE(chain_sequence)`, `UNIQUE(evidence_id,
  custody_sequence)`, `custody_action` CHECK, indexes, `REVOKE ALL … FROM
  PUBLIC`, `GRANT INSERT, SELECT`, `REVOKE UPDATE, DELETE, TRUNCATE`.
- No Alembic (Decision B carried forward). Both scripts are mounted with `001`
  into the Postgres init dir and run in filename order.
- Opt-in `test_provenance_migration_v1_and_v2_coexist_and_verify` proves a v1
  and a v2 event coexist and the whole chain verifies intact after `002` runs.

## 7. Exact File List

**Created (17):**

```
SPRINT-7-PROPOSAL.md                                          (planning artifact, prior turn)
SPRINT-7-STATUS.md                                            (this file)
docs/engineering/sprint-7-design.md
libs/python/emg-audit-client/src/emg_audit_client/provenance.py
libs/python/emg-audit-client/src/emg_audit_client/custody.py
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/custody_hashing.py
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/custody_store.py
libs/python/emg-audit-pipeline/tests/test_provenance.py
libs/python/emg-audit-pipeline/tests/test_backward_compat_hashing.py
libs/python/emg-audit-pipeline/tests/test_custody_stores.py
libs/python/emg-audit-pipeline/tests/test_custody_integrity.py
libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_custody.py
services/audit/src/emg_audit_service/routers/custody.py
services/audit/tests/test_custody_api.py
services/audit/tests/test_provenance_api.py
tools/seed-data/postgres/002_audit_provenance.sql
tools/seed-data/postgres/003_evidence_custody.sql
```

**Modified (22):**

```
# governance / status / process docs (7)
ARCHITECTURE_STATUS.md, EMG_PRODUCT_VISION.md, README.md, CHANGELOG.md,
SPRINT-6-STATUS.md, docs/engineering/security-limitations.md,
docs/engineering/testing-strategy.md
# package READMEs (3)
libs/python/emg-audit-client/README.md, libs/python/emg-audit-pipeline/README.md,
services/audit/README.md
# emg-audit-client (3)
src/emg_audit_client/__init__.py        (+provenance/custody exports; v0.2.0)
src/emg_audit_client/event.py           (+schema_version, +provenance, +bounds)
src/emg_audit_client/protocols.py       (+CustodyEventStore)
# emg-audit-pipeline (4)
src/emg_audit_pipeline/__init__.py      (+custody + provenance-validation exports; v0.2.0)
src/emg_audit_pipeline/hashing.py       (version-aware canonicalization)
src/emg_audit_pipeline/stores.py        (persist schema_version + provenance)
src/emg_audit_pipeline/validation.py    (provenance validation/redaction)
# services/audit (5)
src/emg_audit_service/authn.py          (require_audit_custodian, svc-audit)
src/emg_audit_service/main.py           (register custody router; v0.2.0)
src/emg_audit_service/schemas.py        (custody views/responses)
src/emg_audit_service/store.py          (custody store provider)
tests/conftest.py                       (custody store fixture/override)
```

**Deleted:** none.

Counts: **17 created, 22 modified, 0 deleted** (verified via
`git status --porcelain --untracked-files=all` and `git diff --name-only`).

## 8. Quality-Gate Results

| Gate | Result |
| --- | --- |
| `pytest libs services --import-mode=importlib` | **248 passed, 14 skipped** (Sprint 6 baseline 202/8; +46 passed / +6 skipped — the 6 new opt-in live-Postgres custody/migration tests) |
| `ruff check libs services` | **All checks passed** |
| `mypy --strict` (each package `src`) | **Success** — emg-audit-client (6 files), emg-audit-pipeline (7), services/audit (11) |
| `black --check` (Sprint 7 files) | **Clean** (43 files) |
| JSON validation | `emg-realm.json` valid |
| YAML validation | `docker-compose.yml`, `services/audit/service.yaml` valid |
| SQL validation | `002`/`003` parse; parens balanced; `003` has `REVOKE ALL … FROM PUBLIC` + INSERT/SELECT-only + `REVOKE UPDATE/DELETE/TRUNCATE` |
| Secret/token leakage sweep | Clean — no raw tokens/secrets logged or persisted; matches are token *validation* code, redaction patterns, and docstrings |
| Golden v1 hash gate | **Green** — Sprint 6 records byte-for-byte verifiable |
| Full Sprint 1–6 regression | Green, unmodified; identity `AuditEventSink` Protocol + `record_*` sites unchanged; audit forwarding still OFF by default |
| Final security-focused review (working-tree diff) | **APPROVE** — no blocking defects, no high-risk findings, no scope violations; independently re-verified test/file counts, golden hash, provenance field-completeness, forged-field rejection, and governance-doc accuracy |

Note: a repo-wide `black --check` also flags 5 **pre-existing** `services/identity`
files that Sprint 7 did not touch (not in the Sprint 7 diff) — out of scope for
this sprint.

## 9. Scope Confirmation

- **FEAT-04-4 not implemented** — no query/reporting/classification-aware read
  surface, no export, no UI. FEAT-04-4 appears in source only as deferral
  comments. EPIC-04 remains incomplete.
- **EPIC-05 not started; Sprint 8 not started** — no Module 7 work.
- **No Modules 7–10 files touched** (`services/knowledge-graph`, `retrieval`,
  `ai-orchestration`, `decision-intelligence`, `authz` all unchanged).
- **No new ADR; no new role** (roles remain `service-account`, `svc-identity`,
  `svc-authorization`, `svc-audit`).
- **No frozen architecture doc changed** (`git status -- docs/architecture/`
  empty).
- **No Sprint 6 record rewritten or mutated** — `001_audit_events.sql` unchanged;
  version-1 hashing byte-identical (golden gate green); migration is additive.

## 10. Known Limitations & Technical Debt

Full list in `docs/engineering/security-limitations.md`. Sprint 7 highlights:

- **Provenance is producer-asserted** (tamper-evident once stored, but not
  independently attested against an external source of truth).
- **Custody immutability is application/role-enforced, not absolute** — a Postgres
  superuser can still alter storage; the custody hash chain *detects* it.
- **Custody integrity uses a hash chain, not PKI signatures** (deliberate; PKI
  would need a new ADR).
- **Classification-aware reads, human/compliance access, reporting, and any UI
  are FEAT-04-4** (deferred).
- **Technical debt carried forward unchanged, by approval** (no proven Sprint-7
  defect required fixing them): the duplicated service-token validator and
  PostgreSQL connection pooling / async-safe DB access. To be resolved with
  FEAT-04-4 or before production load.
- **Still first-tier persistence**: single-node Postgres, plain idempotent init
  SQL (no Alembic), no partitioning/retention/HA.

## 11. Suggested Commit Message

```
feat(audit): Provenance Record Model + Chain-of-Custody (Sprint 7)

Complete EPIC-04's provenance and digital-evidence data model in an approved
controlled split — FEAT-04-2 and FEAT-04-3 only. FEAT-04-4 (Audit Query &
Reporting Interface) is deferred to the immediate next sprint; EPIC-04 remains
incomplete and EPIC-05 blocked until it lands.

- emg-audit-client: ProvenanceRecord (+ TransformationStep, EventRef) as an
  optional field on AuditEvent, plus a server-assigned event schema_version;
  CustodyEvent/SubmittedCustodyEvent + CustodyEventStore protocol + CustodyQuery.
- emg-audit-pipeline: version-aware canonical hashing (v1 byte-for-byte
  identical to Sprint 6 so every existing record re-verifies; v2 hashes
  provenance), provenance validation/redaction, and a separate append-only
  chain-of-custody ledger (in-memory + Postgres) with a global hash chain, a
  per-evidence custody sequence, advisory-lock serialization, and integrity
  that detects mutation/deletion/gaps/invalid rows without ever raising a 500.
- services/audit: additive POST/GET /audit/custody/events and
  GET /audit/custody/integrity, least-privilege svc-audit-only; POST /audit/events
  now accepts optional provenance. FEAT-04-1 surface unchanged.
- tools/seed-data/postgres/002_audit_provenance.sql (additive columns, no row
  rewrite) and 003_evidence_custody.sql (new append-only table, REVOKE ALL FROM
  PUBLIC, INSERT/SELECT-only role). Idempotent SQL, no Alembic.
- Merge-blocking golden Sprint-6 v1 hash-compatibility test; full provenance +
  custody unit/HTTP suites; opt-in Postgres migration + 25-thread concurrency.

Backward compatibility: no published Sprint 6 record is rewritten, re-hashed,
migrated, or mutated; 001_audit_events.sql unchanged.

Scope: FEAT-04-2 + FEAT-04-3 only. No FEAT-04-4, no EPIC-05, no Modules 7-10,
no new role, no new ADR. Custody integrity uses the existing hash chain (no
PKI). Technical debt (duplicated validator; connection pooling) carried forward
unchanged by approval.

Refs: FEAT-04-2, FEAT-04-3, Module 6, Engineering Backlog v1.0 §6
```

## 12. Suggested Pull Request

**Title:** `Sprint 7: Audit Provenance + Chain-of-Custody (FEAT-04-2, FEAT-04-3)`

**Description:**

> Completes the provenance and digital-evidence data model for EPIC-04 in an
> approved **controlled split**: **FEAT-04-2 (Provenance Record Model)** and
> **FEAT-04-3 (Digital Evidence Chain-of-Custody)** only. **FEAT-04-4 (Audit
> Query & Reporting Interface) is deferred** to the immediate next sprint and
> must land before EPIC-05 / Module 7 begins. **EPIC-04 remains incomplete
> until FEAT-04-4 is delivered.**
>
> **What's in this PR**
> - A versioned `ProvenanceRecord` (source system/component, originating
>   actor/principal, correlation id, event vs. ingest time, classification,
>   transformation history, parent/source refs, evidence origin/collection
>   method, schema version) as an optional field on audit events.
> - **Version-aware canonical hashing**: version-1 events hash byte-for-byte as
>   in Sprint 6 (every existing record re-verifies); version-2 events hash
>   provenance. Guarded by a **merge-blocking golden hash test**.
> - A **separate append-only chain-of-custody ledger** with a global hash chain,
>   per-evidence custody sequence, advisory-lock serialization,
>   `(source_principal, custody_event_id)` idempotency, and integrity that
>   detects mutation, deletion, global-chain breaks, per-evidence gaps, and
>   schema-violating rows — always as an explicit result, never a 500.
> - Additive `services/audit` custody endpoints (least-privilege, `svc-audit`);
>   `POST /audit/events` now accepts optional provenance.
> - Idempotent SQL `002` (additive provenance columns, no row rewrite) and `003`
>   (new append-only custody table, INSERT/SELECT-only role, `REVOKE ALL FROM
>   PUBLIC`).
>
> **What's explicitly NOT in this PR**
> - FEAT-04-4 (query/reporting, classification-aware reads, export, UI); any
>   EPIC-05 / Module 7–10 work; any new role; any new ADR; PKI/digital-signature
>   custody; a shared `emg-service-auth` package; connection pooling; Sprint 8.
>
> **Backward compatibility (please review):** no published Sprint 6 record is
> rewritten, re-hashed, migrated, or mutated; `001_audit_events.sql` is
> unchanged; the golden v1 hash gate is green.
>
> **Immutability boundary:** append-only for both audit and custody is an
> application/DB-role guarantee; a Postgres superuser can still alter storage,
> which the hash-chain integrity verifications *detect*. Custody integrity uses a
> hash chain, not PKI.
>
> **Definition of Done:** this audit/provenance change needs an organizational
> **Security Reviewer sign-off** before merge.
>
> **Quality gates:** pytest 248 passed / 14 skipped (opt-in only), ruff clean,
> mypy --strict clean, black clean (Sprint 7 files), JSON/YAML/SQL valid, secret
> sweep clean, full Sprint 1–6 regression green.

---

**Stopping here per instruction: nothing has been committed, pushed, or merged.**
Sprint 7 (FEAT-04-2 + FEAT-04-3) is **complete — pending merge**; its
security-focused review concluded **APPROVE**. The formal organizational
Security Reviewer sign-off required by the Definition of Done remains
outstanding and is not claimed here. FEAT-04-4 is the approved next-sprint
deliverable that closes EPIC-04.
