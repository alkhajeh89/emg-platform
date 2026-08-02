# EMG P-02 Evidence Ledger Contract Addendum

**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Status:** Draft
**Decision Date:** TBD
**Baseline:** `develop` HEAD

---

# A. Authority and Scope

**FACT:** P-02 identifies the absence of an implemented `EvidenceLedgerRepository`.

**FACT:** The accepted architecture defines `EvidenceLedgerRepository` as an independent persistence capability.

**PURPOSE:** This addendum establishes the minimum architectural contract required before implementation and prevents implementation-driven invention of repository semantics.

---

# B. Proven Constraints

**FACT:** `V001__baseline.sql` defines the `evidence_ledger` table with the following persisted fields:

- `tenant_id`
- `seq`
- `evidence_id`
- `prev_hash`
- `entry_hash`
- `source`
- `locator`
- `source_principal`
- `captured_at`
- `payload`

**FACT:** The persistence schema already reserves storage for the Evidence Ledger.

**FACT:** Phase 2 architecture identifies the Evidence Ledger as an independent persistence capability.

**FACT:** Repository operations are tenant-scoped through `tenant_id`.

**FACT:** The Evidence Ledger is independent of the GraphStore write path.

---

# C. Explicit Non-goals

This addendum does **not** authorize:

- New API routes.
- Automated ingestion pipelines.
- Background workers.
- User interfaces.
- Event sourcing.
- Changes to GraphStore ownership.
- Changes to Mutation Ledger ownership.
- Changes to ADR-028.
- Any implementation beyond defining the architectural contract.

---

# D. Current Contract

**FACT:** PostgreSQL remains the authoritative persistence engine for the Evidence Ledger.

**FACT:** Existing schema defines a hash-chain using:

- `prev_hash`
- `entry_hash`

**FACT:** Existing schema provides tenant partitioning through `tenant_id`.

**FACT:** Existing schema provides ordered entries through `seq`.

---

# E. Repository Boundary

**FACT:** `EvidenceRef` already exists within `emg-memory-graph`.

**RECOMMENDATION:** The repository should expose an internal persistence model (`EvidenceEntry`) representing:

- EvidenceRef
- seq
- prev_hash
- entry_hash

No public API contract is introduced by this addendum.

---

# F. Transaction Boundary

**RECOMMENDATION:**

Repository implementations should perform each append within a single PostgreSQL transaction to preserve consistency.

**OPEN DECISION:**

The repository contract does not currently define how concurrent sequence allocation shall be performed.

Architecture Board approval is required.

---

# G. Integrity

**FACT:**

The persistence schema models a chained ledger through `prev_hash` and `entry_hash`.

**INFERENCE:**

A chained ledger normally implies integrity verification.

**OPEN DECISION:**

The repository contract does not define:

- when integrity verification occurs;
- how much of the chain must be verified;
- repository behavior when corruption is detected.

---

# H. Security and Tenant Isolation

**FACT:**

The repository is partitioned by `tenant_id`.

**RECOMMENDATION:**

Repository implementations should scope every persistence operation by `tenant_id`.

Authorization and classification policies remain outside the scope of this contract.

---

# I. Acceptance Scope

Following Architecture Board approval, the implementation is expected to satisfy the approved repository contract.

Implementation acceptance criteria are intentionally deferred until unresolved architectural decisions are approved.

---

# J. Open Architecture Decisions

The following items remain intentionally unresolved.

They require explicit Architecture Board approval before implementation.

1. Canonical serialization format.
2. Hash input ordering.
3. Hash algorithm confirmation.
4. First-entry convention.
5. Sequence arbitration.
6. Duplicate `evidence_id` semantics.
7. Integrity verification scope.
8. Failure model.
9. Recovery and replay behavior.
10. Future schema evolution.
11. Repository-level authorization boundaries.

---

# K. Expected Implementation Scope (After Approval)

Expected implementation is limited to:

- Internal repository contract.
- PostgreSQL repository implementation.
- Repository tests.

No GraphStore changes.

No API changes.

No mutation pipeline changes.

No ADR changes.

---

# L. Approval Record

**Status:** Draft.

**Implementation is not authorized until the unresolved architecture decisions identified in Section J receive formal Architecture Board approval.**
