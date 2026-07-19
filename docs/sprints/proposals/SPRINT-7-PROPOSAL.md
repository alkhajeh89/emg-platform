# Sprint 7 Implementation Proposal — EPIC-04 Audit Completion

**Status:** Proposal only — **no code written, nothing committed/pushed/merged.**
Awaiting approval before implementation begins.

**Branch:** `feature/sprint-7-audit-completion` (verified current).

**Repository:** `/Users/mak/Documents/GitHub/emg-platform`.

**Authoritative source:** the frozen `docs/architecture/EMG_Engineering_Backlog_v1.0.md`
(§3 Features, §6 Sprint Planning, §7 Dependencies), Module 6 (Audit, Provenance
& Digital Evidence), ADR-015, ADR-016, and the shipped Sprint 6 implementation.

---

## 1. Repository-State Verification

| Check | Command | Result |
| --- | --- | --- |
| Repo root | `git rev-parse --show-toplevel` | `/Users/mak/Documents/GitHub/emg-platform` ✓ |
| Current branch | `git branch --show-current` | `feature/sprint-7-audit-completion` ✓ (matches expected) |
| Working tree | `git status` | clean; up to date with `origin/feature/sprint-7-audit-completion` ✓ |
| Recent history | `git log --oneline -5` | tip `1fe6bc7` (Merge PR #6, Sprint 6) → `732591f` (feat audit Sprint 6) → `59a2c0c` (Merge PR #4, Sprint 5) … ✓ |
| Base after Sprint 6 merge | `git merge-base HEAD develop` | `1fe6bc7…` ✓ (branch is based on develop at the Sprint 6 merge) |
| Sprint 6 merge present | `git merge-base --is-ancestor 1fe6bc7 HEAD` | true; `1fe6bc7` is HEAD (Merge PR #6, Sprint 6) ✓ |

**Conclusion:** state matches every expectation. Sprint 6 (FEAT-04-1) is merged
to `develop` as `1fe6bc7`; this branch is a clean starting point for Sprint 7.
No contradiction found.

**One accuracy defect found (not code):** the five governance/status docs still
describe Sprint 6 as *"Complete — pending merge"* with *"current branch
`feature/sprint-6-audit-event-pipeline`"*. That is now stale — Sprint 6 **is
merged**. See §14 and §18; this must be corrected before (or as step 0 of)
implementation.

---

## 2. Backlog Interpretation for Sprint 7

The frozen Backlog and the executed history disagree by one sprint of audit
work, and both facts matter:

- **Frozen Backlog §6, row 6:** Sprint 6 = EPIC-04, *"Complete audit and
  provenance"*, Key Deliverables **FEAT-04-2, 04-3, 04-4**, exit *"US-04
  acceptance criteria met."* Row 7 = EPIC-05 core ontology (FEAT-05-1).
- **Executed history:** FEAT-04-1 slipped from the Backlog's Sprint 5 row into
  the executed Sprint 6, which then delivered **FEAT-04-1 only** and explicitly
  deferred FEAT-04-2/03/04 (see `sprint-6-design.md` §"Explicit exclusions",
  `security-limitations.md` §"Deferred to later sprints").

So the *content* the Backlog assigned to "Sprint 6" (the three remaining EPIC-04
features) has shifted forward by one executed sprint. The branch name
`feature/sprint-7-audit-completion` and the user constraint *"Do not start
EPIC-05"* both confirm the intent: **Sprint 7 completes EPIC-04**, and EPIC-05
(FEAT-05-1) is explicitly **not** pulled forward.

**Dependency constraint (Backlog §7, Master Plan §17):** EPIC-05 *depends on*
EPIC-04; *"No module begins implementation before every module it depends on has
passed its own acceptance criteria."* Therefore EPIC-04 must be **complete**
before EPIC-05 starts — which means all three remaining features must land
before Sprint 8, not just some of them.

---

## 3. Recommended Sprint 7 Scope

**Recommendation: implement all three remaining EPIC-04 features —
FEAT-04-2 (Provenance Record Model) + FEAT-04-3 (Digital Evidence
Chain-of-Custody) + FEAT-04-4 (Audit Query & Reporting Interface) — completing
EPIC-04.** Internal build order: **04-2 → 04-3 → 04-4** (dependency order, §5).

This is the "another backlog-supported sequencing" that most faithfully honours
the frozen plan: the Backlog itself grouped exactly these three as one *"Complete
audit and provenance"* sprint (16 story points total: 5 + 8 + 3), and the
dependency table requires EPIC-04 to be *complete* — not partially complete —
before EPIC-05.

**This was assessed, not assumed.** Candidate scopes were compared (§5). The
three are tightly coupled (custody references provenance/evidence origins; the
query surface must expose both provenance and custody), 04-4 is the smallest
feature (3 pts), and splitting forces a two-phase data-model migration that
*increases* backward-compatibility risk to Sprint 6 records.

**Sizing caveat (honest):** 16 net-new points + the two tech-debt items that
become *required* once the Postgres query path is exercised (§17) is at the top
end of a single healthy sprint, and Sprint 6 demonstrated how a "small" audit
feature expands under security review. **De-scope trigger (fallback, not the
recommendation):** if the team's re-baselined velocity (Backlog Risk #4) cannot
absorb it, split as **Sprint 7 = FEAT-04-2 + FEAT-04-3** and **Sprint 7b =
FEAT-04-4**, keeping 04-4 as an immediate fast-follow *before* EPIC-05. This
preserves the dependency gate while reducing single-sprint load. It is the only
supported way to reduce scope; dropping 04-2 or 04-3 is not (they are the core
of "provenance & digital evidence" and block EPIC-05).

---

## 4. Features Explicitly Deferred

- **FEAT-05-1 (Core Ontology, EPIC-05)** and everything downstream — **not
  started.** Sprint 7 does not touch Modules 7–10 or `services/knowledge-graph`,
  `services/retrieval`, `services/ai-orchestration`,
  `services/decision-intelligence`.
- **PKI / asymmetric digital signatures for custody** — deferred. FEAT-04-3's
  *"digital signature **or** hash requirements"* is satisfied by the existing
  hash-chain mechanism (§7). Introducing key management / crypto material would
  be a new architectural element requiring an ADR — out of scope.
- **Human compliance-officer UI and BFF** — deferred to EPIC-10 (ADR-014).
  FEAT-04-4 is a *backend query surface* only; no UI is introduced (§11).
- **Message-queue ingestion, table partitioning, retention/purge, HA/DR,
  external hash anchoring / write-once media** — later infrastructure
  (EPIC-11/12), unchanged from Sprint 6's documented boundaries.
- **Alembic / migration framework** — remains a documented later item, though
  Sprint 7's added scripts raise its priority (§9, §16).

---

## 5. Rationale for the Recommended Sequencing

Candidate-scope assessment (all figures from Backlog §8 story points):

| Candidate | Points | Verdict |
| --- | --- | --- |
| FEAT-04-2 only | 5 | **Rejected.** Leaves EPIC-04 incomplete → blocks EPIC-05 start (§7 dependency). Provenance without a custody ledger or query surface delivers little end-user-visible value and still forces a second audit sprint. |
| FEAT-04-2 + 04-3 | 13 | **Viable fallback only.** Completes the *data* side of "provenance & digital evidence" but leaves the audit records unqueryable beyond FEAT-04-1's minimal surface; still requires a fast-follow before EPIC-05. Use only if velocity forces a split (§3). |
| **FEAT-04-2 + 04-3 + 04-4** | **16** | **Recommended.** Matches the Backlog's own bundling; completes EPIC-04 in one increment; unblocks EPIC-05 cleanly; single coherent data-model + migration; 04-4 is only 3 pts. |
| Pull FEAT-05-1 forward | — | **Forbidden.** Violates "Do not start EPIC-05" and the dependency gate. |

Internal build order **04-2 → 04-3 → 04-4** because:

1. **FEAT-04-2 (Provenance)** extends the audit event's origin model and the
   canonical hash (version-aware). Everything else reads it.
2. **FEAT-04-3 (Chain-of-Custody)** is a new append-only ledger whose custody
   records reference evidence origins/collection methods introduced by 04-2.
3. **FEAT-04-4 (Query & Reporting)** is the read surface over *both* the
   provenance-enriched audit events and the custody ledger, so it must come
   last to expose the complete field set.

Meeting acceptance criteria **without redesigning Module 6:** yes. Module 6 is
formally *"Audit, Provenance & Digital Evidence"* (ADR-015 & ADR-016 §1 row 3);
provenance and chain-of-custody are already inside the frozen module scope. All
three features extend the Sprint 6 hybrid architecture (contract library +
pipeline library + thin `services/audit` shell) additively — no architectural
redesign, no new ADR (§7, §16).

---

## 6. Proposed Acceptance-Criteria Table

The Backlog provides one canonical story per epic (US-04, already met by
FEAT-04-1) and requires each remaining Feature to be *groomed into stories of
that same depth during the sprint before implementation* (§4, §13). The
following are **proposed** acceptance criteria derived from the §3 Feature
descriptions, Module 6, and the user's A/B/C analysis areas — to be ratified at
Sprint 7 grooming, not invented here.

**FEAT-04-2 — Provenance Record Model** (traces: Backlog §3 "Source/actor/
timestamp/method tracking"; Module 6; analysis area A)

| # | Proposed criterion |
| --- | --- |
| 2.1 | An audit event can carry a provenance record: source system, source component, originating actor, originating service principal, correlation id, event timestamp **and** distinct ingestion timestamp, and classification (several already exist on `AuditEvent`; the new structure consolidates + versions them). |
| 2.2 | Provenance captures transformation history (ordered steps) and parent/source event references, plus evidence origin and collection method. |
| 2.3 | Provenance is **schema-versioned**; every record self-identifies its version. |
| 2.4 | Provenance fields are part of the canonical hash for version-2 events, so tampering with provenance is detected by integrity verification. |
| 2.5 | Malformed / oversized / sensitive-key provenance is rejected before persistence (reuse Sprint 6 validation + redaction guards). |
| 2.6 | **Every existing Sprint 6 (version-1) record remains readable and re-verifies to its stored hash** (§12). |

**FEAT-04-3 — Digital Evidence Chain-of-Custody** (traces: Backlog §3 "Evidence
integrity and custody tracking"; Module 6; analysis area B)

| # | Proposed criterion |
| --- | --- |
| 3.1 | A custody transfer record captures: evidence identifier, custodian identity, prior custodian, transfer timestamp (server-assigned UTC), transfer reason, and custody action (acquire/transfer/hold/release). |
| 3.2 | Custody records are **append-only** (no update/delete API; DB role INSERT/SELECT only) and carry a per-evidence **custody sequence** plus a global hash-chain link. |
| 3.3 | Tamper detection: a hash chain over custody records detects out-of-band mutation (same mechanism as FEAT-04-1). |
| 3.4 | **Gap detection**: a missing custody sequence number for an evidence item is reported. |
| 3.5 | **Duplicate handling**: a repeated custody-event idempotency key is a no-op, scoped to `(source_principal, custody_event_id)` (mirrors the Sprint 6 P5 fix). |
| 3.6 | Custody writes/reads use existing roles only (`svc-audit`); no new role. |
| 3.7 | Integrity verification for the custody chain never raises on a malformed stored row — it reports `intact=false` (mirrors Sprint 6 P4). |

**FEAT-04-4 — Audit Query & Reporting Interface** (traces: Backlog §3 "Backend
query surface for audit records"; analysis area C)

| # | Proposed criterion |
| --- | --- |
| 4.1 | Query audit events by actor, correlation id, time range **and** classification, module, action, outcome, source system, and evidence identifier (filters combine with AND). |
| 4.2 | Results are **paginated** (stable cursor/keyset over `sequence_number`) and **ordered** deterministically (by sequence/time). |
| 4.3 | Reads are **classification-aware**: records above the requester's authorized classification band are excluded/redacted, enforced via the existing `emg-policy-engine` PEP — no new role. |
| 4.4 | A backend **export/report** endpoint returns a filtered result set in a structured format (JSON/CSV); **no UI** (EPIC-10). |
| 4.5 | Custody chains are queryable by evidence id / custodian / time range, and a custody-integrity endpoint reports tamper/gaps. |
| 4.6 | Appropriate indexes exist for every new filterable column; query latency is acceptable on a representative volume. |
| 4.7 | The FEAT-04-1 minimal query (US-04) continues to work unchanged (backward compatible). |

EPIC-04 exit: **US-04 remains met** (unchanged from Sprint 6) and the three
Feature-level criteria above are demonstrated, satisfying the Backlog §6 row-6
exit condition *"Complete audit and provenance."*

---

## 7. Architecture-Impact Assessment

| Dimension | Assessment |
| --- | --- |
| **Frozen architecture** | No change. Module 6 already = "Audit, Provenance & Digital Evidence" (ADR-015, ADR-016 §1). All three features are within frozen module scope. |
| **New ADR required?** | **No.** No architectural contradiction is introduced. Custody integrity reuses the established hash-chain tamper-evidence pattern (Backlog allows "digital signature **or** hash"). Classification-aware reads reuse the existing ABAC PEP. A new ADR would be required *only if* PKI/digital-signature custody or a new role were introduced — both are explicitly out of scope. |
| **Pattern** | Extends the Sprint 6 hybrid: `emg-audit-client` (contract) + `emg-audit-pipeline` (implementation) + thin `services/audit` shell. Additive only. |
| **New service?** | No. `services/audit` gains routers/endpoints; no new service, no activation of `services/authz` or any Module 7–10 service. |
| **Cross-module contracts** | Additive optional fields on shared `emg-audit-client` models → `/libs` change → cross-team review required (Master Plan §14, CONTRIBUTING §4). |
| **Observability (ADR-015)** | New endpoints/decision points get instrumentation per DoD; audit and telemetry stores stay distinct (ADR-015 §Decision). |
| **Ownership (ADR-016)** | `CODEOWNERS` already routes `/services/audit/` → `@emg/audit-provenance`; Module 6 owner CISO/CDO (joint), steward Audit Platform Team. Security-reviewer sign-off required (§11, §13). |

---

## 8. Proposed Data-Model Changes

**FEAT-04-2 — Provenance (additive, versioned):**

- `emg-audit-client`: add to `AuditEvent` / `SubmittedAuditEvent`:
  - `schema_version: int = 1` (server-stamped: `2` when provenance present, else `1`).
  - `provenance: ProvenanceRecord | None = None` — a new frozen pydantic model:
    `source_system`, `source_component`, `originating_actor`,
    `originating_principal`, `event_time` vs `ingest_time` (already on the
    event; provenance references them), `classification`,
    `transformation_history: tuple[TransformationStep, ...]`,
    `parent_event_refs: tuple[EventRef, ...]` (each an
    `(source_principal, event_id)` + optional `event_hash`),
    `evidence_origin`, `collection_method`.
- All new fields **optional with defaults** → existing producers/tests
  construct v1 events unchanged.

**FEAT-04-3 — Custody (new, separate ledger — does NOT touch `audit_events`):**

- `emg-audit-client`: new `CustodyEvent` / `SubmittedCustodyEvent` models:
  `custody_event_id` (idempotency), `evidence_id`, `custody_action`
  (`acquire|transfer|hold|release`), `custodian`, `prior_custodian`,
  `transfer_reason`, `classification`, `correlation_id`; server-assigned
  `source_principal`, `custody_sequence` (per-evidence), `chain_sequence`
  (global), `transfer_timestamp`, `ingest_time`, `prev_hash`, `event_hash`.
- New `CustodyEventStore` Protocol (`append` / `query` / `verify_integrity` /
  gap-report) mirroring `AuditEventStore`.

**FEAT-04-4 — Query/reporting (no new persisted entity):** extends `AuditQuery`
(new optional filters + cursor/page_size) and adds a `CustodyQuery` model; adds
read-model view schemas in `services/audit`.

---

## 9. Database-Schema and Migration Plan

Consistent with Sprint 6 Decision B (plain **idempotent** SQL, no Alembic).
All new SQL is `IF NOT EXISTS` / idempotent `GRANT`/`REVOKE`; **no `UPDATE` of
any existing row**.

- **`tools/seed-data/postgres/002_audit_provenance.sql`** (FEAT-04-2):
  - `ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS schema_version INT NOT NULL DEFAULT 1;`
  - `ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS provenance JSONB;`
    (nullable → existing rows valid; existing hashes unaffected because v1
    canonicalization excludes provenance, §12).
  - New indexes: `classification`, `module`, `action`, `outcome`,
    `source_system` (support FEAT-04-4 filters).
  - No re-grant needed (columns inherit table grants); `REVOKE`s unchanged.
- **`tools/seed-data/postgres/003_evidence_custody.sql`** (FEAT-04-3):
  - `CREATE TABLE IF NOT EXISTS evidence_custody_events (...)` — global
    `chain_sequence BIGINT UNIQUE`, per-evidence `custody_sequence`,
    `PRIMARY KEY (source_principal, custody_event_id)`, hash-chain columns,
    `CHECK` on `custody_action`.
  - Indexes: `evidence_id`, `custodian`, `transfer_timestamp`, `classification`.
  - `REVOKE ALL ON evidence_custody_events FROM PUBLIC;`
    `GRANT INSERT, SELECT ON evidence_custody_events TO emg_audit_app;`
    `REVOKE UPDATE, DELETE, TRUNCATE ON evidence_custody_events FROM emg_audit_app;`

**Migration safety on Sprint 6 records:** adding nullable columns never rewrites
existing rows; a migration test (§13) verifies pre-existing v1 rows still
`verify_integrity()` intact after `002` runs. **Growing debt flag:** Sprint 7
adds two more hand-written scripts; recommend adopting a migration framework
before the schema grows further (§16, open decision).

---

## 10. API Changes (`services/audit`, additive)

| Endpoint | Change | Auth |
| --- | --- | --- |
| `POST /audit/events` | Accepts optional `provenance`; server stamps `schema_version`. Existing callers unaffected. | recognized service principal (unchanged) |
| `GET /audit/events` | New optional filters (`classification`, `module`, `action`, `outcome`, `source_system`, `evidence_id`) + cursor pagination (`cursor`, `page_size`) + ordering; existing params unchanged. | `svc-audit`, **classification-aware** |
| `POST /audit/custody/events` | **New.** Append a custody transfer (append-only, idempotent). | `svc-audit` |
| `GET /audit/custody/events` | **New.** Query custody chain by evidence id / custodian / time range. | `svc-audit`, classification-aware |
| `GET /audit/custody/integrity` | **New.** Verify custody chain; report tamper + gaps. | `svc-audit` |
| `GET /audit/events/export` (or `/audit/reports`) | **New.** Filtered structured export (JSON/CSV), backend only. | `svc-audit`, classification-aware |
| `GET /audit/integrity` | Unchanged for the audit chain; custody covered by its own endpoint. | `svc-audit` |

No endpoint is removed or breaks; the FEAT-04-1 surface is preserved.

---

## 11. Authorization and Classification-Control Plan

- **No new roles** (hard constraint). Reuse existing `svc-audit` for all
  audit-plane reads, custody writes, and custody reads; audit-event *ingest*
  stays open to any recognized service principal (unchanged).
- **Classification-aware reads:** integrate `emg-policy-engine`'s PEP into the
  query/report path. A policy evaluates the requester's authorized
  classification band (from roles/scopes/attributes) against each record's
  `classification` (`UNCLASSIFIED < INTERNAL < CONFIDENTIAL < SECRET`, per
  `emg_common_types.Classification`); records above the band are excluded or
  field-redacted. The *mechanism* is delivered now; the exact band mapping for
  principals is an open decision (§16) — Sprint 7 makes it explicit and
  configurable rather than inventing a "compliance-officer" role.
- **Human compliance-officer direct access is not required now** — FEAT-04-4 is
  a backend surface for a future BFF (EPIC-10). Delivering the classification
  mechanism keeps that future path safe without a UI or a new role.
- **Security-reviewer sign-off is REQUIRED** for Sprint 7 (Master Plan §15,
  Backlog §14: any change touching classification, provenance, or audit
  behavior). This is a real, distinct sign-off gate, not the code-level review.

---

## 12. Backward-Compatibility Strategy (the linchpin)

The Sprint 6 canonical hash (`emg-audit-pipeline/hashing.py`) has a **fixed key
set**; `recompute_event_hash` rebuilds it from stored fields. Adding provenance
must not change any existing hash.

- **Version-aware canonicalization.** `canonical_payload` gains a
  `schema_version` branch: the **v1 path is byte-identical to today** (no
  provenance keys) so every Sprint 6 record reproduces its stored `event_hash`;
  the **v2 path** appends the provenance keys. `recompute_event_hash` dispatches
  on `event.schema_version`.
- **Golden backward-compat test (must-have, §13):** a Sprint-6-era serialized
  event + its stored hash re-verifies under Sprint 7 code. `verify_integrity()`
  over a v1-only store stays `intact`.
- **No silent rewriting, no mutation.** Existing published events are never
  updated or re-hashed; provenance is only ever hashed for *new* v2 events.
  New fields are optional; reading a pre-migration row yields
  `provenance=None`, `schema_version=1`.
- **Custody is a separate table** → zero migration impact on `audit_events`.

---

## 13. Testing Plan

Mapped to the user's area-F checklist (all default-offline; Postgres/concurrency
suites opt-in and skipped by default, mirroring Sprint 6):

- **Provenance positive/negative** — valid provenance persists + hashes;
  malformed/oversized/sensitive-key provenance rejected (`emg-audit-pipeline`,
  `services/audit`).
- **Provenance-chain / tamper** — v2 event tamper on any provenance field
  detected by integrity verification.
- **Backward-compat (critical)** — golden v1 record re-verifies; v1-only store
  `verify_integrity` intact; mixed v1/v2 store integrity intact.
- **Custody sequence** — ordered custody transfers produce contiguous
  per-evidence `custody_sequence` and a valid global chain.
- **Custody tamper + gap** — mutated custody row detected; a missing custody
  sequence reported by gap detection; malformed stored row → `intact=false`,
  never raises.
- **Custody duplicate** — repeated `(source_principal, custody_event_id)` is a
  no-op.
- **Classification-aware query authz** — a reader below a record's band is
  excluded/redacted; at/above band sees it; `svc-audit`-only enforced;
  non-audit principal denied.
- **Pagination + ordering** — stable cursor paging over `sequence_number`; no
  duplicates/skips across pages; deterministic order.
- **Filter combinations** — actor × classification × module × action × outcome ×
  source_system × time-range AND-combinations.
- **Migration tests (opt-in Postgres)** — run `002`/`003`; pre-existing v1 rows
  still intact; custody table append-only (INSERT/SELECT-only role denied
  UPDATE/DELETE).
- **Concurrency (opt-in Postgres)** — concurrent custody appends serialize via
  advisory lock; unique + contiguous chain sequence; single valid chain (mirrors
  Sprint 6's FEAT-04-1 concurrency test).
- **Secret/token leakage** — provenance/custody free-text + metadata redaction;
  no tokens/secrets/Authorization headers persisted.
- **Full Sprint 1–6 regression** — entire existing suite green unmodified;
  identity `AuditEventSink` Protocol + `record_*` sites unchanged; audit
  forwarding still OFF by default (no behavior change).

---

## 14. Documentation Plan

- **New:** `docs/engineering/sprint-7-design.md` (the ratified design, produced
  at implementation start), and `SPRINT-7-STATUS.md` (at completion).
- **Update:** `ARCHITECTURE_STATUS.md`, `EMG_PRODUCT_VISION.md`, `README.md`,
  `CHANGELOG.md` (Sprint 7 entry), `docs/engineering/security-limitations.md`
  (custody/provenance boundaries; retire resolved debt; note remaining),
  `docs/engineering/testing-strategy.md` (Sprint 7 test sections),
  `services/audit/README.md`, `libs/python/emg-audit-*/README.md`.
- **Governance-accuracy correction (do first — see §18):** mark Sprint 6
  **merged** (PR #6, `1fe6bc7`), set current branch/sprint to Sprint 7, and
  update Module 6 status, across the five stale docs.

---

## 15. Exact Files Likely to Be Created / Modified

**Likely created (~18–24):**

```
docs/engineering/sprint-7-design.md
SPRINT-7-STATUS.md
tools/seed-data/postgres/002_audit_provenance.sql
tools/seed-data/postgres/003_evidence_custody.sql
libs/python/emg-audit-client/src/emg_audit_client/provenance.py      (ProvenanceRecord, TransformationStep, EventRef)
libs/python/emg-audit-client/src/emg_audit_client/custody.py         (CustodyEvent, SubmittedCustodyEvent, CustodyQuery)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/custody_store.py  (In-memory + Postgres custody stores)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/custody_integrity.py
libs/python/emg-audit-pipeline/tests/test_provenance.py
libs/python/emg-audit-pipeline/tests/test_custody_stores.py
libs/python/emg-audit-pipeline/tests/test_custody_integrity.py
libs/python/emg-audit-pipeline/tests/test_backward_compat_hashing.py
libs/python/emg-audit-pipeline/tests/test_integration_live_postgres_custody.py  (opt-in)
services/audit/src/emg_audit_service/routers/custody.py
services/audit/src/emg_audit_service/routers/reports.py
services/audit/tests/test_custody_api.py
services/audit/tests/test_query_reporting_api.py
services/audit/tests/test_classification_aware_reads.py
(optional, if tech-debt consolidation approved) libs/python/emg-service-auth/**  (shared validator package)
```

**Likely modified (~12–16):**

```
libs/python/emg-audit-client/src/emg_audit_client/event.py           (+schema_version, +provenance)
libs/python/emg-audit-client/src/emg_audit_client/query.py           (+filters, +pagination)
libs/python/emg-audit-client/src/emg_audit_client/protocols.py       (+CustodyEventStore, extend AuditEventStore.query)
libs/python/emg-audit-client/src/emg_audit_client/__init__.py        (exports)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/hashing.py     (version-aware canonicalization)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/stores.py      (persist/read provenance + schema_version; new filters + pagination)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/validation.py  (provenance validation/redaction)
libs/python/emg-audit-pipeline/src/emg_audit_pipeline/__init__.py
services/audit/src/emg_audit_service/routers/events.py               (new query params)
services/audit/src/emg_audit_service/schemas.py                      (provenance/custody views)
services/audit/src/emg_audit_service/main.py                         (register custody/reports routers)
services/audit/src/emg_audit_service/store.py                        (custody store wiring; optional pool)
services/audit/pyproject.toml                                        (+emg-policy-engine dep for PEP)
docs/engineering/security-limitations.md, testing-strategy.md
ARCHITECTURE_STATUS.md, EMG_PRODUCT_VISION.md, README.md, CHANGELOG.md
```

Exact counts finalized at implementation. **No deletions expected.**

---

## 16. Risks and Open Decisions

| # | Risk / open decision | Recommendation |
| --- | --- | --- |
| R1 | **Sprint size** — 16 pts + required pooling debt may exceed one sprint. | Confirm against re-baselined velocity at grooming; use the §3 de-scope trigger (04-4 → fast-follow) if needed. **User decision.** |
| R2 | **Classification clearance-band mapping** for principals is undefined (no clearance attribute today). | Deliver the PEP mechanism + a configurable band mapping; keep `svc-audit`'s band explicit. **User decision on the mapping.** |
| R3 | **Custody sequence scope** — per-evidence vs. global chain. | Do both: global hash chain (tamper-evidence) + per-evidence `custody_sequence` (gap detection). |
| R4 | **Shared `emg-service-auth` package** (tech-debt #1) adds scope/points. | Recommended within Sprint 7 *if* 04-4 lands (§17); **user decision** — flagged, not assumed. |
| R5 | **Adopt Alembic now?** Sprint 7 adds 2 more hand-written scripts. | Not blocking; recommend scheduling migration tooling before the next schema change. **User decision.** |
| R6 | **Export format / size limits** for FEAT-04-4 reports. | Bounded JSON/CSV, classification-filtered, paginated; no unbounded dumps. |
| R7 | **Backward-compat hashing regression** is the highest-consequence risk. | Version-aware canonicalization + golden test as a merge-blocking gate (§12, §13). |

---

## 17. Assessment of Sprint 6 Technical Debt

Both items are *safe today* (in-memory default store, identity forwarding off).
Classification requested:

1. **Duplicated service-token validator** (`services/audit/authn.py` vs
   `services/identity`) — **Required within Sprint 7 *if* FEAT-04-4 is in
   scope; otherwise acceptable documented debt.** Rationale: FEAT-04-3 (custody
   auth) and FEAT-04-4 (classification-aware reads) materially expand the audit
   service's authorization surface on top of a validator that "can drift."
   Consolidating into a shared `emg-service-auth` **library** (not a new
   service, not a new role, not an ADR) is the right moment. **Not blocking**
   (it works and is tested on both sides). Flagged as **open decision R4** —
   deliberately not auto-implemented.

2. **PostgreSQL connection pooling / async-safe DB access** — **Required within
   Sprint 7 if the Postgres query/report path is exercised under load
   (FEAT-04-4); otherwise separate hardening sprint.** Rationale: 04-4
   introduces real concurrent read (pagination/filter/export) alongside ingest;
   a single shared `psycopg` connection with blocking calls in `async def`
   handlers becomes an availability concern. **Not blocking** and **not a
   correctness defect** (concurrency correctness is already guaranteed by the
   advisory lock + `UNIQUE` + retry). Pair `psycopg_pool` + executor offload (or
   sync handlers) with 04-4's delivery.

Neither item **blocks** Sprint 7. Summary: both are *"required within Sprint 7,
paired with FEAT-04-4"* under the recommended scope; both downgrade to
*"separate hardening sprint / acceptable documented debt"* under the split
fallback where 04-4 is deferred.

---

## 18. Recommendation on Governance-Document Correction (before implementation)

**Yes — a small documentation-accuracy correction is required first.** The five
docs are now factually stale after the Sprint 6 merge (`1fe6bc7`, PR #6):

| File | Stale reference | Correct to |
| --- | --- | --- |
| `ARCHITECTURE_STATUS.md` | "Current Branch: `feature/sprint-6-…`"; "Current Sprint: Sprint 6 (complete — pending merge)"; Sprint 6 row "Complete (pending merge)"; "Last Updated" narrative | Sprint 6 **Complete (merged, PR #6, `1fe6bc7`)**; Current Branch `feature/sprint-7-audit-completion`; Current Sprint 7 (EPIC-04 completion, in progress) |
| `EMG_PRODUCT_VISION.md` | Sprint 6 row wording; roadmap sprint pointer | Sprint 6 **Complete (merged)**; add Sprint 7 = EPIC-04 completion |
| `README.md` | "Engineering Phase … Sprint 6 … complete — pending merge"; Sprint 6 block "pending merge"; "Sprint 7 … not started" | Sprint 6 **merged**; Sprint 7 in progress (EPIC-04 completion) |
| `CHANGELOG.md` | "Sprint 6 … — complete (pending merge)" under `[Unreleased]` | Move Sprint 6 to a released/merged heading; open a Sprint 7 `[Unreleased]` section |
| `SPRINT-6-STATUS.md` | "Status: … pending merge"; "Branch: `feature/sprint-6-…`"; closing "pending merge" lines | Mark **Merged** (PR #6, `1fe6bc7`); it is a historical record — annotate, don't rewrite history |

This is a **governance-accuracy fix, not scope** — analogous to the Sprint 6
closure pass. Recommend doing it as **step 0** of Sprint 7 (or a tiny standalone
doc-correction commit) so the repository does not carry contradictory
Sprint-6-status text while Sprint 7 is underway. **Not yet edited** — per
instruction, this proposal stops before any change.

---

## Stop

This is a proposal only. **No code or docs were modified; nothing was committed,
pushed, or merged.** Awaiting your approval of: (a) the recommended scope
(all three EPIC-04 features vs. the split fallback), (b) the open decisions in
§16 (esp. R1 sizing, R2 classification bands, R4 shared-auth package, R5
Alembic), and (c) the §18 governance-accuracy correction, before implementation
begins.
