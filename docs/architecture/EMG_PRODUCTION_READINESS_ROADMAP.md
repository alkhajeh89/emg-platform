# EMG Production Readiness Roadmap

Original audit date: 2026-07-27
Current reconciliation baseline: `develop` at `69e2267` (2026-08-09), after
RC-1C through RC-1H.
Protocol: `docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`
Scope: living release-governance roadmap. Historical addenda below retain
their point-in-time baselines; this current reconciliation governs present
status.

This document is a point-in-time audit of the EMG repository against its own
architecture baseline (`ARCHITECTURE_STATUS.md`, `EMG_ARCHITECTURE_DECISION_REGISTER.md`,
the Engineering Backlog, and the security/technical-debt registers), aimed at
answering one question: **what stands between the current repository state
and a first production-ready release, and in what order should it be closed?**

## RC1 Current Reconciliation — 2026-08-09

### Implemented and repository-validated

- ADR-028 Audit Projector, including D-51 bounded graceful shutdown,
  tenant-scoped identities, durable retry, crash recovery, and backlog state.
- ADR-038 delegated human identity, including Studio BFF Authorization Code +
  PKCE, RFC 8693 token exchange, downstream validation, and synchronous
  fail-closed audit attribution.
- Authoritative mutation-to-Audit PostgreSQL E2E reconciliation with stable
  `kg-mutation:{mutation_uuid}:{ordinal}` event identities and duplicate replay.
- EL-10 evidence-ledger hardening in V008: structural constraints, genesis
  enforcement, and an owner-binding append-only trigger. Application chain
  verification remains the cryptographic integrity authority.
- ADR-039 provider-neutral backup, WAL/PITR, restore, manifest, retention,
  encryption-wrapper, and evidence-anchor tooling.
- ADR-040 runtime image supply-chain implementation: build once, Trivy gate,
  GHCR immutable digests, keyless Cosign signing, GitHub provenance, generated
  deployment bundle, and complete rollback digest set.
- ADR-041 production provisioning implementation: governed database bootstrap,
  Audit migration authority, canonical projector identity inventory,
  per-tenant Keycloak provisioning, derived Audit allow-list, External Secret
  references, ordered stages, and fail-closed consistency validation.
- Production Kustomize foundation and provider-neutral deployment templates.

### Open operational prerequisites

- Protected GitHub `production-release` environment and a witnessed first
  GHCR/OIDC/Cosign release using production governance.
- Production tenant inventory, actual credentials, secret-store integration,
  TLS/certificates, and environment-specific egress rules.
- Operator/CD enforcement of the ADR-041 Job-to-Deployment sequence.
- Environment selections for backup scheduling, KMS/encryption custody, and
  cross-region storage, plus a witnessed production recovery rehearsal.
- Production observability backends, dashboards, alerting, and accreditation.

### Post-v1

- Continuous Neo4j projection daemon (TD-002).
- DAST and dedicated IaC security scanning.
- Proposed ADR-019/020/021 implementation and GraphRAG, AI orchestration, and
  Decision Intelligence product surfaces.

## Historical ADR-028 Acceptance Addendum — 2026-08-09

ADR-028 is now **Accepted** and authorizes implementation of the dedicated
Audit Projector. The decision resolves deployment topology, tenant-scoped
projector Service Principals, tenant-partitioned dispatch claims, at-least-once
delivery, deterministic idempotency, bounded durable retry/reschedule,
poison/exhausted preservation, crash recovery, graceful shutdown, backlog
observations, and the single-replica RC1 scalability boundary. The underlying
production-readiness finding remained open at acceptance. RC-1C subsequently
implemented the consumer and RC-1E proved authoritative cross-service
reconciliation; the current reconciliation above supersedes this point-in-time
status.

## Historical Governance Reconciliation Addendum — 2026-08-01

**Reconciliation baseline:** `develop` at `aefc82c` (PR #37).

This addendum is deliberately narrow. It re-verifies only the Knowledge Graph
mutation-delivery facts changed since the original 2026-07-27 audit; it does
not re-audit or restate unrelated roadmap findings.

- ADR-027 Revision 5 is Accepted and implemented through Stage 4 Phase 4A.
  The original five-route HTTP transport landed in `08949e0`; the governance
  and code conformance work landed in `f59cb4b` and `0ea7c74`, respectively,
  and was merged to `develop` by PR #37 at `aefc82c`.
- ADR-028 remains **Referenced, not written, not begun**. That status was
  re-verified at this baseline and is unchanged by this reconciliation.
- The ADR-027 decision to provide a Knowledge Graph write path is closed.
  Scope for ADR-027 Stage 4 Phases 4B–4E remains undefined and is tracked as
  D-A-004; this roadmap does not define it.
- The separate `emg-knowledge-pipeline` service binding and the Neo4j serving-
  projection binding remain open integration work. Phase 4A completion does
  not imply that either binding is complete.

## Historical Persistence Reconciliation Addendum — 2026-08-03

**Reconciliation baseline:** `develop` at `e578d31` (PR #55).

Deliberately narrow, in the same style as the 2026-08-01 addendum above. It
re-verifies only the persistence facts changed since they were last recorded and
re-audits nothing else. The original 2026-07-27 findings and the table below are
preserved as written.

**Now closed:**

- **Neo4j serving-projection binding** — no longer open. `services/knowledge-graph`
  composes the lazy Neo4j projection and current reads prefer it with
  read-repair, falling back to PostgreSQL (P-01, `cdbf0ca`, PR #52). This
  supersedes the 2026-08-01 bullet above naming it open integration work. The
  `emg-knowledge-pipeline` service binding remains open.
- **PostgreSQL connection pooling** — implemented as a lazy, bounded pool with
  explicit lifecycle ownership at the service boundary (P-04, `8afadb9`,
  `78a3919`, PR #51).
- **Runtime privilege breadth** — migration V006 narrows the runtime role's
  `UPDATE` grants to specific columns (P-03, `b99b9af`, PR #50).
- **Unbounded dispatch retry** — mutation-dispatch claims are bounded by an
  explicit `max_attempts` (P-05, `8972aa7`, PR #48).
- **TD-003** (`neo4j/lazy.py` unit coverage) — resolved by P-01.

**Status corrections to the table below:**

- The **ADR-028** row states "Referenced, not written, not begun". That was
  accurate at `aefc82c`. ADR-028 Revision 1 has since been written and merged
  (`96702a2` … `9b9d2ab`, PRs #47 and #49). Its repository status is
  **Draft — not Accepted, `Decision Date: TBD`** at that historical baseline.
  The 2026-08-09 acceptance addendum above supersedes that governance status.
  At that historical baseline, no `mutation_dispatch` audit consumer existed
  and cross-service reconciliation was not delivered. RC-1C and RC-1E close
  that finding; see the current reconciliation above.

**New and unchanged open items:**

- **P-02 evidence ledger.** The `EvidenceLedgerRepository` is implemented
  (PR #55) under an accepted contract that authorized the repository contract
  **only**. There is no ingestion wiring, API, worker, UI, or product
  capability, and no production caller. Its EL-10 schema hardening — a
  database-enforced append-only trigger, `prev_hash NOT NULL`, `seq >= 1`, and
  hash-format checks — is **required before the ledger is relied upon as an
  evidentiary record** and is not yet applied.
- **TD-002** (continuous `ProjectionWorker` daemon) remains open and accepted.
- Backup, restore, PITR, and retention procedure are now governed by **ADR-039**
  (`EMG_ADR-039_BACKUP_PITR_AND_RECOVERY_GOVERNANCE.md`), ratifying the implementation at
  `infra/backup/` and `tools/backup/`. Cross-region replication, PostgreSQL HA/failover,
  encryption/KMS and scheduler product selection, and the first witnessed production
  rehearsal remain unspecified deployment/operations readiness work (ADR-039 §15).

Current persistence detail: `docs/engineering/persistence-architecture.md` and
`docs/engineering/persistence-operations.md`.

## Historical Security Reconciliation Addendum — 2026-08-03

**Reconciliation baseline:** `develop` at `47cbeac` (PR #56).

Deliberately narrow, matching the convention of the two addenda above. It
corrects only §4 "Known Security Limitations", which the Architecture Baseline
Review found **overstates** remaining risk because three of its four
production-blocking findings have since been closed in code. **The original §4
findings below are preserved as written; nothing is erased.**

**Closed since the 2026-07-27 audit:**

- **§4 item 1 — audit clearance-based read authorization is now PEP-enforced.**
  `services/audit/src/emg_audit_service/authorization.py` defines
  `AuditReadAuthorizer` ("Ask the PEP which classifications this verified
  principal may read"), producing an `AuditReadScope` of allowed
  classifications. `routers/events.py:121` passes
  `allowed_classifications=scope.classifications` into the query path, so the
  caller cannot widen its own clearance. The original finding — "classification
  *filtering* ships in FEAT-04-4; classification *enforcement* does not" — no
  longer describes the repository.
- **§4 item 2 — the Knowledge Graph recognized-client allow-list exists.**
  `services/knowledge-graph/src/emg_knowledge_graph_api/authn.py:63-74` defines
  `_RECOGNIZED_CLIENTS`, mapping four registered client identifiers to their
  required realm roles, and `validate()` rejects any unrecognized `azp`/
  `client_id` and any token missing its registered roles. This is the same
  shape as `services/audit` and `services/identity`. The claim that "any
  validly-signed token for the configured realm/audience is accepted" is no
  longer accurate.
- **§4 item 3, second clause — audit is now a second PEP-enforcing resource
  server.** The statement "no resource server besides `services/knowledge-graph`
  currently calls the PEP for enforcement" is superseded by item 1 above. The
  first clause stands: `/authz/check` on the identity service remains
  introspection by deliberate design and is not a PEP gate.
- **§4 item 4 — CI security and container scanning exist.**
  `.github/workflows/ci.yml` runs a `security` job (dependency vulnerability
  scanning via `pip-audit` against the hash-locked production lockfile, secret
  scanning, and SBOM generation with uploaded artifacts), a
  `container-security` job (Trivy, action pinned by commit SHA, with
  `security-events: write`), and a `release-provenance` job. The claim of
  "**zero** SAST, DAST, dependency/SCA vulnerability scanning, secret scanning,
  or container/IaC scanning" is no longer accurate. DAST and IaC scanning
  remain absent.

**Explicitly unchanged and still open:**

- **§4 item 5 — production secrets management.** Every secret in the repository
  remains an explicitly labelled local-development placeholder; `SecretStr` is
  used so values are not rendered in logs or tracebacks. There is still no
  centralized secrets platform. FEAT-11-3 is not started. **This gap is open.**
- Every other production-readiness gap recorded in §5, §6, §7, §8, and §9 is
  unchanged by this addendum: observability collection, dashboards and alerting;
  deployment topology and IaC; backup, restore, PITR and DR (subsequently
  governed by **ADR-039**, 2026-08-09 — see §2 above; deployment-level items
  such as HA/failover and product selection remain open per ADR-039 §15); data
  retention; the continuous `ProjectionWorker` daemon (TD-002); the audit
  dispatch consumer; the P-02 EL-10 evidence-ledger schema hardening; and
  ADR-027 Stage 5 production rollout.

**Governance corrections applied the same day (context only, not a readiness
change).** ADR-022, ADR-023, and ADR-024 were ratified as Accepted after
verification that the implementation already conformed; ADR-028 was registered
at its true **Draft** status; the ADR-014/015/016/017 baseline-publication
condition was discharged; and the dangling ADR-031 citation in ADR-032 was
replaced with an explicit open dependency now tracked as **D-A-005** (backup,
PITR, and recovery-metadata governance). None of these changed any
architectural decision or any production-readiness position. *(D-A-005 was
subsequently superseded by ADR-039 on 2026-08-09; see §2 above.)*

---

## 1. Architecture vs. Engineering Status

All ten Modules (1–10) are architecture-approved and frozen. Engineering
status is materially behind architecture status for most modules. This gap
is expected and documented — architecture approval is a design gate, not a
delivery signal — but it is the single most important fact for release
planning: **a majority of the frozen architecture has no corresponding code.**

| Module | Architecture | Engineering | Production-relevant gap |
| --- | --- | --- | --- |
| 1–3 (Foundation) | Frozen | Complete | None |
| 4 (Identity) | Frozen | Implemented through Sprint 3 | Live service, tested |
| 5 (Authorization & Policy) | Frozen | Baseline complete; first live enforcement adopter is ADR-025 | `services/authz` itself is still an empty scaffold — the library (`emg-policy-engine`) is the real, live enforcement path instead |
| 6 (Audit) | Frozen | EPIC-04 complete; ADR-028 projector, RC-1E authoritative E2E, EL-10, and ADR-041 Audit migrations implemented | Target-environment provisioning, secrets, TLS, release execution, and recovery rehearsal remain operational prerequisites |
| 7 (Knowledge Graph) | Frozen | Query and mutation APIs are live; PostgreSQL is authoritative and Neo4j serving projection/read-repair is composed; mutation audit dispatch is consumed by the Audit Projector | Continuous Neo4j projection daemon remains post-v1; production environment execution remains open |
| 8 (Search / GraphRAG) | Frozen | Scaffolded only | Zero implementation |
| 9 (AI Orchestration) | Frozen | Scaffolded only | Zero implementation |
| 10 (Decision Intelligence) | Frozen | Scaffolded only | Zero implementation |

**Verified directly from the repository** (not from documentation claims):

- `services/authz`, `services/retrieval`, `services/ai-orchestration`,
  `services/decision-intelligence` each contain `service.yaml` + empty
  `src/`/`tests/` directories only. Zero Python files, zero lines of code.
- `libs/python/emg-entity-resolution` has a **0-byte `pyproject.toml`** and
  zero source files — an abandoned or premature scaffold (tracked as open
  decision D-A-002, unresolved).
- The Knowledge Graph query router
  (`emg_knowledge_graph_api/routers/knowledge_graph.py`) remains read-only;
  that router is not the service's complete HTTP surface. The same service
  registers `emg_knowledge_graph_api/routers/mutations.py`, which exposes the
  five ADR-027 Revision 5 mutation routes. The separate ingestion pipeline
  (`emg-knowledge-pipeline`, built in Sprint 10) remains a standalone library
  not wired into a live service path.

---

## 2. ADR Status

| ADR | Title | Status | Production relevance |
| --- | --- | --- | --- |
| ADR-014 | Enterprise Presentation Architecture | Approved — Frozen | No frontend exists yet (EPIC-10 not started) |
| ADR-015 | Unified Enterprise Observability | Approved — Frozen | `emg-telemetry` (149 lines) provides correlation-id plumbing only; no metrics/tracing backend, no dashboards, no alerting (see §5) |
| ADR-016 | Enterprise Ownership Registry | Approved — Frozen | Followed consistently (`service.yaml` owner/steward fields) |
| ADR-017 | Enterprise Capacity & Scalability Model | Approved — Frozen | No implementation (EPIC-11/FEAT-11-4) |
| ADR-018 | Bilingual Enterprise Architecture | Accepted — Foundation invariant | `LanguageCode`/`Locale`/`TextDirection` exist in `emg-common-types`; no UI to validate end-to-end bilingual behavior yet |
| ADR-019 | AI Orchestration Layer | **Proposed** | Architecture-only; zero implementation |
| ADR-020 | Knowledge Ingestion Layer | **Proposed** | Architecture-only; the actual ingestion library (`emg-knowledge-pipeline`) was built separately under FEAT-05-2 and is not yet reconciled with this ADR's design |
| ADR-021 | Enterprise API Strategy | **Proposed** | Architecture-only; no API gateway exists |
| ADR-022/023/024 | KG Revision Build / History / Query Engine | Implemented | Live, tested |
| ADR-025 | KG Tenant & Authorization Model | **Accepted — implemented** | Live; one open follow-up (no client-id allow-list registry, see §4) |
| ADR-026 Rev 2 | KG Classification Enforcement Model | **Accepted — fully implemented** | Live; this session's ADR-026 final blocker fix is the most recent change |
| ADR-027 Revision 5 | KG Mutation API | **Accepted — implemented through Stage 4 Phase 4A** | Five-route HTTP mutation transport and final conformance are merged on `develop` at `aefc82c` (PR #37); the write-path decision is closed. Later-phase scope is not defined here. |
| ADR-028 | Audit reconciliation | **Accepted and implemented** | Dedicated Audit Projector, D-51 shutdown, tenant partitioning, durable retry, crash recovery, and authoritative RC-1E E2E proof are repository-validated |
| ADR-038 | Human identity delegation | **Accepted and implemented** | Phase 2B Studio BFF, RFC 8693 token exchange, downstream validation, and fail-closed audit attribution are repository-validated |
| ADR-039 | Backup, PITR and recovery governance | **Accepted and implemented in repository** | Provider-neutral mechanics are validated; environment scheduler/KMS/cross-region choices and witnessed recovery rehearsal remain open |
| ADR-040 | Runtime image supply chain | **Accepted and implemented in repository** | Workflow and release evidence are validated; protected environment and live first-release proof remain open |
| ADR-041 | Production provisioning | **Accepted and implemented in repository** | Bootstrap, Audit migrations, identity inventory, Keycloak provisioning, derived allow-list, secrets wiring, and consistency validation exist; operator/CD execution remains open |

ADR-001 through ADR-013 do not exist in this repository and must not be
treated as approved or implied.

---

## 3. Open Architecture Decisions (blocking or advisory)

From `EMG_ARCHITECTURE_DECISION_REGISTER.md`, still **Open**:

- **D-A-001 — Module Numbering Governance.** Three incompatible numbering
  schemes coexist (Module 1–10, Phase 0/1/2, reference-architecture `M01…Mxx`).
  Documentation-governance risk only; **does not block any implementation**,
  but will keep costing reviewer time on every future ADR until resolved.
- **D-A-002 — Entity Resolution Ownership.** `emg-entity-resolution` is an
  empty scaffold while `emg-memory-graph` already has its own, separate,
  complete entity-resolution engine. **No future work may depend on
  `emg-entity-resolution` until this is resolved** — this is a binding
  constraint already recorded, and it directly affects how any future
  Knowledge Graph ingestion or connector-sourced entity matching should be
  designed.

---

## 4. Known Security Limitations (production-blocking subset)

Pulled from `docs/engineering/security-limitations.md` and the ADR-025/026
governance records — limited here to items that matter for a *production*
release, not every documented scope boundary:

1. **Audit read authorization is implemented.** Audit queries derive allowed
   classifications through the existing PEP/Policy Engine; callers cannot
   widen their clearance.
2. **Knowledge Graph recognized-client enforcement is implemented.** Accepted
   clients are bound to required roles rather than accepting any validly
   signed realm token.
3. **`/authz/check` remains introspection by design.** It is not a substitute
   for a resource-server PEP; Knowledge Graph and Audit perform their own
   fail-closed enforcement.
4. **CI security controls are implemented but not exhaustive.** Dependency
   vulnerability, secret, and container scanning plus SBOM/provenance controls
   exist. DAST and dedicated IaC scanning remain post-v1 candidates.
5. **Production secret references are implemented; secret custody is
   environment-owned.** External Secret resources contain remote references
   only. The target environment must install the operator/store, supply values,
   and govern access and rotation.

---

## 5. Infrastructure & Operability Gap (EPIC-11 / EPIC-12)

The repository now contains a production Kustomize foundation, hardened
workload manifests, NetworkPolicy boundaries, External Secret references,
one-shot migration/bootstrap/provisioning jobs, ADR-041 stage validation, and
the ADR-040 runtime release workflow. Release and rollback evidence generation
is implemented; production resources remain parameterized and deliberately
non-deployable until resolved by the release workflow and environment owners.

The remaining gap is operational rather than absence of repository artifacts:

- A Kubernetes cluster, ingress/TLS, approved external PostgreSQL/Neo4j/
  Keycloak endpoints, and environment-specific egress controls must be
  supplied by the target environment.
- External Secrets Operator and a provider-specific secret store must be
  installed; the repository contains references, never secret values or a
  vendor selection.
- The protected GitHub `production-release` environment and live
  GHCR/OIDC/Cosign execution must be configured and witnessed.
- Operator/CD must enforce the ADR-041 cross-resource completion sequence;
  Kubernetes annotations and readiness probes do not create that dependency.
- Metrics/tracing backends, dashboards, alerting, accreditation, HA/failover,
  and environment recovery rehearsal remain open.
- DAST and dedicated IaC security scanning remain post-v1 unless release
  governance promotes them into the RC1 gate.

Repository-ready is therefore not the same as production-environment-proven.

---

## 6. Technical Debt (from `docs/engineering/technical-debt.md`)

| ID | Item | Severity | Status |
| --- | --- | --- | --- |
| TD-001 | `mypy --strict` not enforced in CI | Low | **Resolved** (Phase 1) |
| TD-002 | No continuous `ProjectionWorker` daemon | Low | Open, accepted — fine for current read-repair model, but relevant once near-real-time projection freshness is needed |
| TD-003 | `neo4j/lazy.py` driver-construction path lacks unit coverage | Low | **Resolved by P-01** |
| TD-004 | Parallel project-status tracking systems (Phase-N vs. Module/Sprint) | Low | Open, accepted — documentation debt only |

None of these are release-blocking on their own; TD-004 compounds D-A-001
(both are documentation-governance debt) and should be resolved in the same
pass.

---

## 7. Prioritized Roadmap to First Production-Ready Release

Ordering follows the Engineering Master Plan's module-dependency gate ("no
module begins before every module it depends on has passed acceptance") and
this repository's own precedent of treating governance/documentation
cleanup as cheap, high-leverage work that should not be deferred behind
larger features.

The Phase 0–4 labels in this section are production-readiness sequencing
labels only. They do not map to ADR-027 delivery phases or ADR-033 schema
phases, and the frontend work listed below remains a separate future product
track.

### Phase 0 — Governance cleanup (low effort, unblocks nothing technical but reduces review risk on everything after)

1. Resolve **D-A-001** (module numbering) — publish one canonical scheme or
   an explicit mapping table.
2. Resolve **D-A-002** (entity resolution ownership) — either formally
   retire `emg-entity-resolution` or assign it real ownership before any
   future ingestion/connector work is tempted to reference it.
3. Reconcile **TD-004** (parallel status-tracking) in the same pass as
   D-A-001.
4. Apply OBS-A-001's still-pending Option A (fix the dangling "§32"
   citation in `ports/graph_store.py` / `emg-platform-core`'s
   `pyproject.toml`).

### Phase 1 — Security closures completed in repository

6. **Audit clearance-based read authorization — Closed.** Audit reads use the
   existing PEP/Policy Engine and caller clearance cannot widen results.
7. **Knowledge Graph recognized-client allow-list — Closed.** The resource
   server binds accepted clients to required roles.
8. **ADR-038 delegated identity — Closed in repository.** Phase 2B implements
   and validates the BFF, token exchange, downstream validation, and
   fail-closed audit path. Production identity material remains environment-owned.

### Phase 2 — Authoritative persistence and audit closures completed

9. **ADR-027 mutation write path — Closed.** Exactly five authenticated
   mutation routes remain authoritative.
10. **Audit dispatch reconciliation — Closed.** ADR-028 is implemented and
    RC-1E proves the real PostgreSQL mutation → dispatch → projector → Audit
    Service → Audit PostgreSQL path, including retry and duplicate replay.
11. **Evidence-ledger EL-10 — Closed.** V008 supplies structural checks and an
    owner-binding append-only trigger without claiming database-side
    cryptographic chain recomputation.
12. **Neo4j serving binding — Closed.** The lazy projection/read-repair path is
    composed. A continuous projection daemon remains post-v1.

### Phase 3 — Repository foundation complete; execute environment gates

13. Configure the protected `production-release` GitHub environment and prove
    one live GHCR/Cosign/OIDC release with the retained evidence bundle.
14. Supply production tenant inventory, secret values, External Secrets store,
    TLS/certificates, and approved external egress controls.
15. Execute the ADR-041 bootstrap stages through the target operator/CD system,
    waiting for each successful outcome before workload rollout.
16. Configure the environment's backup scheduler, KMS/encryption custody, and
    cross-region storage, then conduct a witnessed recovery rehearsal.
17. Complete production observability, alerting, capacity/HA decisions, and
    organizational accreditation.

### Phase 4 — Post-v1

Continuous Neo4j projection, DAST, dedicated IaC scanning, proposed
ADR-019/020/021 implementation, GraphRAG, AI orchestration, and Decision
Intelligence remain outside the RC1 core release. Their absence must not be
presented as an unfinished RC1 implementation blocker.

---

## 8. Summary Table — What Blocks "First Production-Ready Release"

| Blocker | Category | Phase |
| --- | --- | --- |
| Module numbering / entity-resolution ownership unresolved | Governance | 0 |
| Protected release environment and live GHCR/Cosign/OIDC proof not yet witnessed | Release operations | 3 |
| Production identity inventory and secret values not supplied | Security / Infrastructure | 3 |
| External Secrets store, TLS/certificates, and egress policy not installed for a target | Environment operations | 3 |
| ADR-041 ordered bootstrap not yet executed in production | Provisioning operations | 3 |
| Production recovery rehearsal and environment scheduler/KMS/cross-region choices outstanding | Recovery operations | 3 |
| No metrics/tracing backend or alerting | Observability | 3 |
| No HA/DR realization of ADR-017 | Infrastructure | 3 |
| Continuous projection, DAST, IaC scanning, and Modules 8–10 | Feature/governance scope | 4 (post-v1) |

---

## 9. Remaining Risks

No known architectural violations were found — the frozen architecture
(PolicyEngine/PolicyEnforcementPoint boundaries, dependency direction,
fail-closed security posture) is consistently honored everywhere it has been
engineered. The risks that remain are scope and sequencing risks, not
architectural-integrity risks:

- Repository implementation can be mistaken for target-environment proof.
  Release governance must retain the distinction explicitly.
- The first privileged runtime-image release and the complete ADR-041 stage
  sequence have not yet been witnessed in the production environment.
- Backup/PITR mechanics exist, but scheduler/KMS/cross-region configuration and
  the production recovery rehearsal remain environment-owned.
- D-A-001/D-A-002 are low-risk individually but compound review overhead on
  every future ADR until resolved — recommended to close early precisely
  because they are cheap.
