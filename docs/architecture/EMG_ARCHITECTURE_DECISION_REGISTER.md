# EMG Architecture Decision Register

**Status:** Living register — tracks unresolved and resolved architecture decisions
**Date opened:** 2026-07-25
**Purpose:** These items are identified gaps or ambiguities discovered during
`IMPLEMENTATION_GAP_ANALYSIS.md` and the Phase 3 documentation pass. They are
tracked here explicitly rather than resolved silently. An item only leaves
this register when it is marked **Accepted** with a named decider and a
dated decision — never by a later document simply assuming an answer.

This register follows the same convention already established by
`docs/architecture/backend/BACKEND_DECISION_REGISTER.md` and
`docs/security/SECURITY_DECISION_REGISTER.md`: a decision recorded here does
not constitute approved architecture unless explicitly marked Accepted.

---

## Governance Documents (Non-ADR)

| ID | Type | Status | Approval | Scope and effect |
| :--- | :--- | :--- | :--- | :--- |
| GR-001 | Governance Document — **not an ADR** | **Ratified and Effective (2026-08-01); C-1, C-2, and C-3 satisfied** | Jointly approved by the Office of the CTO and Architecture Board | Governs documentation authority only. It does not redefine product scope or architecture and does not amend the Product Architecture Freeze or any accepted ADR. See `docs/governance/GR-001_EMG_DOCUMENTATION_GOVERNANCE_FRAMEWORK.md`. |
| PD-001 | Freeze Control record — **not an ADR** | **Accepted (2026-08-03)** | Owner: EMG Founder; Architect: EMG Founder; Decision Authority: Project Architect | Affirms the Product Architecture Freeze **without amending it**, and records that the Executive Dashboard remains outside the MVP. Records the computability status of all six frozen Freeze §23 indicators and prohibits placeholder executive metrics in MVP. Creates no architecture decision. See `docs/product/EMG_PD-001_MVP_FREEZE_CONTROL_RECORD.md`. |
| DS-001 | Design authority — **not an ADR** | **Accepted (2026-08-03)** | Owner: EMG Founder; Architect: EMG Founder; Decision Authority: Design System Governance Authority | **Canonical EMG design-system authority**, derived from ADR-014 and binding under ADR-018. Supplies the substance ADR-014 assumed existed when it cited an "approved Enterprise UX Architecture & Design System" that was present only as a stub. Fixes token architecture, typography and bilingual hierarchy, semantic colour roles with an **exclusive classification range**, spacing/grid/density, component admission criteria, classification-safe rendering, WCAG 2.2 AA, RTL rules, motion, and the MVP component inventory. Designates `docs/frontend/design-system/` as derived implementation guidance. Expands no product scope; Dashboard and AI Assistant remain outside MVP per PD-001. Creates no architecture decision. See `docs/enterprise-design/EMG_DESIGN_SYSTEM_BASELINE.md`. |
| DS-002 | Design decision — **not an ADR** | **Accepted (2026-08-03)** | Owner: EMG Founder; Architect: EMG Founder; Decision Authority: Design System Governance Authority | Selects **Institutional Neutral** as the visual identity direction, on the deciding rationale that it preserves maximum headroom for the exclusive classification colour range. Records the rejected alternatives and their trade-offs. Introduces **no logo, no marketing identity, no illustration system, and no final colour values**. See `docs/enterprise-design/EMG_VISUAL_IDENTITY_DECISION.md`. |
| DS-003 | Figma implementation detail — **not an ADR** | **Accepted (2026-08-03)** | Owner: EMG Founder; Architect: EMG Founder; Decision Authority: Design System Governance Authority | Specifies the three-file Figma library structure (Foundations → Components → Product), variable collections and modes for Light/Dark, Comfortable/Compact, and LTR/RTL, naming conventions, variants, publication order, and the archive/deprecation process. **No Figma asset exists**; this describes what is to be built. Decides nothing not already decided in DS-001/DS-002. See `docs/enterprise-design/EMG_FIGMA_LIBRARY_STRUCTURE.md`. |

---

## Architecture Decision Records (ADR-014 – ADR-044)

Thirty ADRs are present in this range. ADR-031 is intentionally absent;
ADR-039 resolved the dangling recovery-governance reference that formerly used
that number. Proposed ADRs remain Proposed regardless of implementation in
adjacent packages.

Canonical index of every ADR number in the current range. Added 2026-08-03 to
close register-completeness finding DOC-4. This section records *governance
metadata only* — it confers no authority (GR-001 Rule 3) and creates no
authority hierarchy; each ADR's own document remains authoritative for its
decisions. Absent numbers are listed explicitly rather than silently omitted.

**Owner / Architect / Decision Authority defaults** are EMG Founder, EMG
Founder, and Project Architect respectively, except where the ADR itself names
a different accountable owner — those are recorded as stated.

| ADR | Title | Status | Owner | Architect | Decision Authority | Decision Date | Governing document | Implementation status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| ADR-014 | Enterprise Presentation Architecture | **Accepted** | CIO function jointly with the design-system owner (per ADR-014 §Governance) | EMG Founder | Project Architect | 2026-07-15; publication condition discharged 2026-08-03 | `EMG_ADR-014_Enterprise_Presentation_Architecture.md` | **Not implemented** — `apps/` contains no client surface |
| ADR-015 | Unified Enterprise Observability | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-15; discharged 2026-08-03 | `EMG_ADR-015_Unified_Enterprise_Observability.md` | **Partial** — ADR-027 emits structured mutation metrics; no collection, storage, dashboards, tracing, or alerting exists |
| ADR-016 | Enterprise Ownership Registry | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-15; discharged 2026-08-03 | `EMG_ADR-016_Enterprise_Ownership_Registry.md` | **Partial** — per-service `service.yaml` owner/steward fields exist; no consolidated platform-wide registry |
| ADR-017 | Enterprise Capacity & Scalability Model | **Accepted** | CTO function jointly with each layer's Accountable Owner (per ADR-017 §1) | EMG Founder | Project Architect | 2026-07-15; discharged 2026-08-03 | `EMG_ADR-017_Enterprise_Capacity_Scalability_Model.md` | **Not implemented** — no capacity model, HA, or DR procedure exists |
| ADR-018 | Bilingual Enterprise Architecture (Arabic + English) | **Accepted** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-018_Bilingual_Enterprise_Architecture.md` | **Implemented** — bilingual content round-trips verified in Phase 2 projection tests |
| ADR-019 | AI Orchestration Layer | **Proposed** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-019_AI_ORCHESTRATION.md` | **Not started** — `services/ai-orchestration` is an empty scaffold |
| ADR-020 | Knowledge Ingestion Layer | **Proposed** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-020_KNOWLEDGE_INGESTION.md` | **Not started** — `emg-knowledge-pipeline` exists but is not reconciled with this ADR and is not wired |
| ADR-021 | Enterprise API Strategy | **Proposed** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-021_ENTERPRISE_API_STRATEGY.md` | **Not started** — no API gateway exists |
| ADR-022 | Knowledge Graph Revision Build Workflow | **Accepted (ratified 2026-08-03)** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-022_KNOWLEDGE_GRAPH_REVISION_BUILD_WORKFLOW.md` | **Implemented** — `KnowledgeGraphApplication.build_revision`; internal orchestration only, not a production mutation ingress (§5.9) |
| ADR-023 | Knowledge Graph Revision History & Navigation | **Accepted (ratified 2026-08-03)** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-023_KNOWLEDGE_GRAPH_REVISION_HISTORY_AND_NAVIGATION.md` | **Implemented** — `GraphRevisionReader`, `RevisionMetadata`, extended `WriteReceipt`, four orchestrator methods |
| ADR-024 | Knowledge Graph Query Engine | **Accepted (ratified 2026-08-03)** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-024_KNOWLEDGE_GRAPH_QUERY_ENGINE.md` | **Implemented** — application-layer query engine with seven HTTP query routes |
| ADR-025 | Knowledge Graph Tenant & Authorization Model | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-27 | `EMG_ADR-025_KNOWLEDGE_GRAPH_TENANT_AUTHORIZATION_MODEL.md` | **Implemented** (Group C, 2026-07-27) |
| ADR-026 (Rev 2) | Knowledge Graph Classification Enforcement Model | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-27 | `EMG_ADR-026_KNOWLEDGE_GRAPH_CLASSIFICATION_ENFORCEMENT_MODEL.md` | **Implemented** (Phase 1 + Phase 2, D1–D13) |
| ADR-027 (Rev 5) | Knowledge Graph Mutation API | **Accepted** | Chief Data Officer (accountable owner, per D-A-004) | EMG Founder | Project Architect | 2026-08-01 | `EMG_ADR-027_KNOWLEDGE_GRAPH_MUTATION_API.md` | **Implemented through Stage 4**; Stage 5 documentation complete, production rollout open |
| **ADR-028** | **Audit Reconciliation** | **Accepted** | EMG Founder | EMG Founder | Project Architect | **2026-08-09** | `EMG_ADR-028_AUDIT_RECONCILIATION.md` | **Implemented and repository-validated** — the dedicated single-replica RC1 Audit Projector consumes tenant-partitioned `mutation_dispatch` audit work with tenant-scoped Service Principals, at-least-once delivery, bounded durable retry, idempotent acceptance, crash recovery, D-51 bounded graceful shutdown, and backlog observations. Authoritative PostgreSQL mutation-to-audit delivery is proven by the RC-1E integration suite. Target-environment provisioning remains an operational prerequisite |
| ADR-029 (Rev 2) | Entity/Relationship Identity, Lifecycle & Supersession Model | **Accepted** | Architecture Board / Chief Data Officer (per D-A-003) | EMG Founder | Project Architect | 2026-07-28 | `EMG_ADR-029_ENTITY_RELATIONSHIP_IDENTITY_LIFECYCLE_SUPERSESSION_MODEL.md` | **Implemented** (`97b211d`) |
| ADR-030 (Rev 4) | Mutation Ledger & Atomic Idempotency | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-30 (SRS-2 amendment) | `EMG_ADR-030_MUTATION_LEDGER_ATOMIC_IDEMPOTENCY.md` | **Implemented** (`2dab646`) |
| **ADR-031** | — | **Absent — no document exists** | — | — | — | — | — | Cited once by ADR-032 §Future Compatibility for backup/PITR schema-version metadata. Verified absent repository-wide on 2026-08-03; the citation has been replaced with an explicit open dependency. Tracked as **D-A-005**. No ADR-031 is authored |
| ADR-032 | Knowledge Graph Schema Versioning & Evolution | **Accepted** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-032_KNOWLEDGE_GRAPH_SCHEMA_VERSIONING_AND_EVOLUTION.md` | **Partial** — mutation-path negotiation implemented; read-path adoption governed separately |
| ADR-033 (Rev 2) | Schema Registry and Negotiation Service | **Accepted** | EMG Founder | EMG Founder | Project Architect | — | `EMG_ADR-033_SCHEMA_REGISTRY_AND_NEGOTIATION_SERVICE.md` | **Partial** — complete through Phase 3 (`5288392`); Phase 4 and production normalizers not started |
| ADR-034 | Security State and Service Trust | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-07-30 | `EMG_ADR-034_SECURITY_STATE_AND_SERVICE_TRUST.md` | **Implemented** (SRS-2) |
| **ADR-035** | Human Principal Authentication | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-035_HUMAN_PRINCIPAL_AUTHENTICATION.md` | **Implemented and repository-validated in Phase 2B** — Studio BFF terminates Authorization Code + PKCE S256, holds opaque server-side sessions, and keeps bearer credentials out of the browser. Production client values, TLS, and Keycloak deployment remain environment-owned |
| **ADR-036** | Application and BFF Boundary | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-036_APPLICATION_BFF_BOUNDARY.md` | **Implemented and repository-validated in Phase 2B** — `apps/studio-bff` is the mandatory browser boundary, is not a PEP, has no datastore access, and uses ADR-038 delegation for downstream human execution. Production deployment remains an operational prerequisite. Closes D-F-006 |
| **ADR-037** | Decision Domain Model | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-03 | `EMG_ADR-037_DECISION_DOMAIN_MODEL.md` | **Not implemented** — this branch contains no Decision ontology model, Decision Query Service, Decision HTTP API, Studio aggregate backend, or Studio frontend. The accepted contract introduces no new `NodeType`, `EdgeType`, or mutation route. |
| **ADR-038** | Human Identity Delegation Architecture | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-07 | `EMG_ADR-038_Human_Identity_Delegation_Architecture.md` | **Implemented and repository-validated in Phase 2B** — OAuth 2.0 Token Exchange preserves the Human Principal and independently attributable BFF Acting Service, with single-audience isolation, tenant and clearance integrity, bounded lifetime, downstream validation, and synchronous fail-closed audit attribution. The mandatory Keycloak 25 capability suite passed; production realm/TLS configuration remains environment-owned |
| **ADR-039** | Backup, PITR and Recovery Governance | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-09 | `EMG_ADR-039_BACKUP_PITR_AND_RECOVERY_GOVERNANCE.md` | **Implemented** — ratifies the already-implemented physical backup, WAL/PITR, retention, manifest, evidence-anchor, and encryption-wrapper mechanics at `infra/backup/` and `tools/backup/`. Introduces no new code or mechanism. Resolves **D-A-005** and the dangling ADR-031 citation in ADR-032 §Future Compatibility. Documents one permanent, intentional manifest-validation residual (schema cannot express cross-sibling tablespace-OID uniqueness without a format change; the canonical Python validator remains the sole enforcement point). |
| **ADR-040** | Runtime Image Supply Chain | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-09 | `EMG_ADR-040_RUNTIME_IMAGE_SUPPLY_CHAIN.md` | **Implemented and repository-validated** — the tag-triggered release workflow builds each governed runtime image once, blocks publication on the Trivy gate, publishes immutable digests to GHCR, performs keyless Cosign signing and identity verification, creates GitHub runtime provenance, and generates complete deployment and rollback evidence. The protected `production-release` environment, live GHCR/OIDC/Cosign first-release proof, and retention policy are operational prerequisites |
| **ADR-041** | Production Provisioning Ownership & Bootstrap Contract | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-09 | `EMG_ADR-041_PRODUCTION_PROVISIONING_OWNERSHIP_AND_BOOTSTRAP_CONTRACT.md` | **Implemented and repository-validated** — bounded database bootstrap creates the governed roles, `emg_audit_migrator` owns a distinct Audit migration stream, `emg_audit_projector` exists before V007, one validated projector inventory drives Keycloak/runtime/Audit allow-list configuration, and staged jobs plus consistency validation fail closed. Production values and operator/CD stage execution remain environment-owned |
| **ADR-042** | Governed Enterprise Search | **Accepted** | EMG Founder | EMG Founder | Project Architect | 2026-08-10 | `EMG_ADR-042_GOVERNED_ENTERPRISE_SEARCH.md` | **Implemented and repository-validated** — PostgreSQL V010 search representations, deterministic exact/prefix search, encrypted lifetime-governed cursors, authorization-safe bounded pagination, retention/work controls, Audit integration, Studio BFF forwarding, and Studio search/explorer surfaces are implemented. Target-environment execution remains an operational prerequisite |
| **ADR-043** | Identity Durable Refresh State Database and Migration Authority | **Accepted; Amendment 1 Accepted (2026-08-14) — revised (2026-08-14), narrowly remediated (2026-08-14), further remediated (2026-08-14), authority-linearization remediated (2026-08-14), accepted after fifth independent review (2026-08-14)** | EMG Founder | EMG Founder | Project Architect | 2026-08-14 | `EMG_ADR-043_IDENTITY_DURABLE_REFRESH_STATE_DATABASE_AND_MIGRATION_AUTHORITY.md` | **Base implementation review blocked on two P0 corrections; first independent review of Amendment 1 did not accept it (P0-A external-authority rollback protection, P0-B enforceable recovery fencing); second independent review found the redesign sound but identified two remaining explicitness gaps (A9.6 fence-release ordering, A9.7/A12 network-fence failure-mode enumeration); third independent review FAILED the amendment on two further material defects — a contradiction between A9.4's migrator-only network fence and A9.6's requirement that the freshly started `emg_identity_app` workload query the same target, and an unverified claim that GCP Secret Manager, AWS Secrets Manager, and Vault KV v2 all natively satisfy the five-capability Approved Recovery Authority contract; fourth independent review FAILED the amendment again on the concurrent-rotation control itself, finding that the "mechanism 3b" read-verify-after-write procedure was not a linearizable serialization primitive — GCP Secret Manager's documented strong consistency covers only direct access to an already-known version number, not the version-history listing the predecessor check depended on, so two coordinators could each observe a stale ordering and each independently conclude their rotation succeeded; fifth independent review PASSED — it confirmed the redefined capability 3 (single authoritative linearization point per transition), mechanism 3a (native CAS) and redefined mechanism 3b (a genuine alternative provider-native serialization primitive, never read-verify-after-write), the eight-property authority qualification gate, the rewritten A3.2 rotation algorithm with A3.2.1 crash semantics, and the extended A12 authority-rotation adversarial tests, under adversarial analysis of the same-predecessor dual-writer race in both interleavings and every named rotation crash point, with no regression in any previously-passing fencing/recovery/privilege control. GCP Secret Manager alone remains disqualified; Vault KV v2 qualifies only conditional on explicit history-retention configuration; no new EMG platform component was introduced. Amendment 1 is Accepted; target execution of its two P0 remediations (replay-resistant recovery-freshness protocol; P0-1 exact legacy-adoption validation, already required by D-6) remains a separate, subsequent implementation review** — Amendment 1 now requires the Approved Recovery Authority to provide platform-guaranteed monotonic non-reused version history plus a serialized-rotation guarantee decided at a single authority-side linearization point (A3 capability 3), satisfiable via native atomic conditional writes (mechanism 3a; Vault KV v2's `cas` parameter, conditioned on deployment configuring sufficient version-history retention) or another genuine provider-native serialization primitive distinct from version creation itself (mechanism 3b — an atomic lease, exclusive lock, or conditional metadata compare-and-set; a read-verify-after-write procedure no longer qualifies as mechanism 3b under any circumstance), gated by an explicit eight-property authority qualification gate, with an authority-rotation algorithm (A3.2) built around one atomic accept/reject step and explicit per-stage crash semantics (A3.2.1). GCP Secret Manager alone no longer qualifies as an Approved Recovery Authority for concurrent generation rotation; it would qualify only if paired with a separately governed native serialization primitive, which this remediation does not select, invent, or authorize. This carries the authority revision alongside the generation through materialization/PostgreSQL/readiness comparisons, and adds a four-part recovery fencing protocol (named fence owner; workload, database-session, and a two-phase network fence — a reconciliation-fence phase restricted to `emg_identity_migrator`, and a separately evidenced readiness-qualification-fence phase admitting only the freshly started `emg_identity_app` workload identity, which does not itself constitute service restoration; mandatory positive evidence per fence and per phase transition). Fence release (A9.6) is an explicit nine-step ordered gate — the Phase 1→Phase 2 network-fence transition is its own evidenced step — requiring fresh-workload startup and independently-proven readiness before any traffic/database-access restoration; the network fence receives explicit fail-closed failure-mode treatment (A9.7) and adversarial test coverage (A12) for both phases, matching the workload and database-session fences, now extended with authority-rotation-layer adversarial tests (dual-writer races and every named rotation crash point). Legacy-adoption catalog-state hardening is clarified as already required by accepted D-6. No new architecture component was required to resolve any finding, including the fourth. Amendment 1 is Accepted (2026-08-14) following the fifth independent review; target execution of its two authorized P0 remediations remains a separate, subsequent implementation review and operational prerequisite |
| **ADR-044** | Recovery Authority: Spanner Transition Authority and GCS Bucket-Locked Immutable Witness | **Accepted (2026-08-16) — accepted after a second independent review of corrected text; the first independent review found one P0 (an unsupported organization-administrator signing-trust-domain claim) and two P1 findings (undisclosed qualification billing-account sharing with `emg-platform-staging`; missing KMS key-lifecycle prerequisite), both corrected in-document with no architecture, protocol, or evidence change** | EMG Founder | EMG Founder | Project Architect | 2026-08-16 | `EMG_ADR-044_RECOVERY_AUTHORITY_SPANNER_TRANSITION_AUTHORITY_AND_GCS_BUCKET_LOCKED_IMMUTABLE_WITNESS.md` | **Ratifies the already-implemented `services/recovery-authority` foundation** (`20a2416` and follow-on commits through `8d66fc6`) and its two committed real-GCP provider-qualification evidence packages under `services/recovery-authority/docs/evidence/adr-043/{real-gcp-safe-qualification,real-gcp-destructive-qualification}/`. Resolves a governance/traceability gap discovered by an independent ADR-043 production-readiness review: the `services/recovery-authority` code and both evidence packages had, since their creation, repeatedly self-identified as implementing "ADR-043," but no accepted architecture decision record for that Spanner-sole-transition-authority + GCS-Bucket-Lock-witness design existed anywhere in the repository — the only Accepted ADR-043 (row above) governs the unrelated Identity refresh-token subsystem. ADR-044 is a new, distinctly-numbered decision record (not an amendment to ADR-043, whose scope explicitly excludes this design) that formally captures the fail-closed Spanner commit-classification model, the epoch state machine and `NEW_EPOCH_REQUIRED` requirement, the GCS witness's create-if-absent/no-overwrite/no-fallback semantics, the content-binding-vs-acceptance-provenance cryptographic separation, the threat model (including the `SIGNING_ADMINISTRATIVE_INDEPENDENCE_REQUIREMENT`, §15A), required IAM separation, the billing-relink operational-recovery-dependency finding and required runbook sequence, and the explicit non-goal that this ADR does not establish production approval or become Identity ADR-043's Approved Recovery Authority. Blocker A: `EXPERIMENTALLY_PASSED`. Production approval: `NOT ESTABLISHED`. **Not implemented as a deployable service** — no production Spanner adapter, no production Signer/KMS adapter, no deployable binary, no IAM manifests, no bootstrap/provisioning mechanism, and no independently-qualified signing administrative-trust-domain exist; these are recorded in ADR-044 §17 as prerequisites for a separate, subsequent implementation review, not authorized by this entry |

**Numbers outside this range.** ADR-001 through ADR-013 do not exist in this
repository and must not be treated as approved or implied.

**Supporting documents, not ADRs.** `EMG_ADR-027_STAGE_0_1_GRAPHSTORE_UNIFICATION_ANALYSIS.md`
(blocking analysis) and `EMG_ADR-027_STAGE_1_IMPLEMENTATION_PLAN.md` (plan only)
are ADR-027 support artifacts. They carry no independent decision authority
(GR-001 Rule 8).

---

## Open Architecture Decisions

| ID | Decision Area | Status | Owner | Evidence | Blocking Questions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| D-A-001 | Module Numbering Governance | **Open** | TBD | `IMPLEMENTATION_GAP_ANALYSIS.md` §6 (Gap 4a), §7 (Gap 4) | Which numbering scheme is canonical? |
| D-A-002 | Entity Resolution Ownership | **Open** | TBD | `IMPLEMENTATION_GAP_ANALYSIS.md` §2 (Gap 1) | Standalone service, part of `emg-memory-graph`, or shared library? |

## Resolved Architecture Decisions

| ID | Decision Area | Status | Owner | Evidence |
| :--- | :--- | :--- | :--- | :--- |
| D-A-003 | Entity/Relationship Identity, Lifecycle & Supersession Model | **Accepted — ADR-029 Revision 2 implemented (2026-07-28)** | Architecture Board / Chief Data Officer | `docs/architecture/EMG_ADR-029_ENTITY_RELATIONSHIP_IDENTITY_LIFECYCLE_SUPERSESSION_MODEL.md`; commit `97b211d`; tag `adr-029-approved-implementation` |
| D-A-004 | ADR-027 Stage 4 Phases 4B–4E Scope Definition | **Accepted — Architecture Board, 2026-08-01** | Chief Data Officer (accountable owner); Architecture Board (approving authority) | `docs/architecture/EMG_ADR-027_KNOWLEDGE_GRAPH_MUTATION_API.md` §2; `docs/specifications/ADR-033/Phase4-Design-Package.md` §11; `docs/specifications/ADR-027/ADR-027_STAGE4_CLOSURE_RECORD.md`; Phase 4A commits `08949e0`, `f59cb4b`, `0ea7c74` and merge commit `aefc82c`; Phase 4B implementation commit `c6c28bb` and PR #45 merge commit `6536b73`; baseline `9588c6d` |
| D-A-005 | Backup, PITR, and Recovery Metadata Governance | **SUPERSEDED BY ADR-039** (recorded Open 2026-08-03; resolved 2026-08-09) | EMG Founder | `docs/architecture/EMG_ADR-039_BACKUP_PITR_AND_RECOVERY_GOVERNANCE.md` (ratifies the implementation at `infra/backup/` and `tools/backup/`); formerly evidenced by `EMG_ADR-032_…md` §Future Compatibility (dangling ADR-031 citation, replaced) and the absence of any backup/PITR/retention/schema-version-in-backup decision under ADR-017 |

## Knowledge Graph ADR Implementation Status

| ADR | Status | Implemented phase |
| :--- | :--- | :--- |
| ADR-027 Revision 5 | **Accepted** | **Stage 4 complete.** Phase 4A implemented (`08949e0`), reconciled (`f59cb4b`, `0ea7c74`), and merged to `develop` (`aefc82c`). Phase 4B implemented at `c6c28bb` and merged through PR #45 at `6536b73`. Phases 4C and 4D are closed as not required. Phase 4E governance and conformance closure is complete. The five-route transport surface is unchanged and authoritative. Stage 5 deployment documentation is complete at `docs/specifications/ADR-027/ADR-027_STAGE5_DEPLOYMENT_AND_ROLLOUT.md`; it documents role, policy-rule, and claim provisioning requirements only and claims no production readiness. Production rollout prerequisites remain open |
| ADR-029 Revision 2 | **Accepted** | Domain implementation complete (`97b211d`) |
| ADR-030 Revision 4 | **Accepted** | Atomic mutation ledger complete (`2dab646`) |
| ADR-032 | **Accepted** | Mutation-path schema negotiation implemented; read-path adoption remains separate |
| ADR-033 Revision 2 | **Accepted** | Infrastructure Foundation complete through Phase 3 (`5288392`); Phase 4 and normalizers not started |
| ADR-034 | **Accepted** | SRS-2 security state, audit confinement, database-role separation, and service-token trust implemented |

## Phase Contract Addenda

Accepted contract addenda that bind a single internal capability defined by a
completed phase architecture. They are not ADRs and do not amend one. Listing
here records approval; it does not confer it (GR-001 Rule 3) — authority rests
on the explicit status and approval recorded in each governing document.

| ID | Title | Status | Approval | Scope and effect | Implementation status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| P-02 | Evidence Ledger Contract Addendum | **Accepted (2026-08-02)** | Owner: EMG Founder; Architect: EMG Founder; Decision Authority: Project Architect | Binds the internal `EvidenceLedgerRepository` contract inside `emg-persistence` only, resolving eleven previously open items as decisions EL-1 through EL-11. Authorizes **no** ingestion wiring, API route, worker, UI, `GraphStore` change, ADR-028 capability, or product capability. Depends on Phase 2 ADR-4 (`docs/phases/phase-2/PHASE2_ARCHITECTURE.md`) and Product Architecture Freeze §12. See `docs/architecture/EMG_P02_EVIDENCE_LEDGER_CONTRACT_ADDENDUM.md`. | **Implemented and hardened** — the repository contract remains internal and V008 now implements EL-10 with fail-closed preflight, `prev_hash NOT NULL`, positive sequence and hash-format constraints, genesis enforcement, and an owner-binding `BEFORE UPDATE OR DELETE` append-only trigger. Application verification still cryptographically recomputes entry hashes and chain links; database constraints provide structural enforcement, not cryptographic recomputation |

### D-A-001 — Module Numbering Governance

**Current conflicting schemes:**

1. `ARCHITECTURE_STATUS.md` — Module 1–10 (Repository Structure through
   Decision Intelligence), with EPIC-01…EPIC-13 and Sprint 1–14 tracking.
2. Phase 0/1/2 roadmap structure (`docs/phases/phase-0`, `phase-1`,
   `phase-2`; current branch `phase2/sprint5-outbox-event-persistence`) —
   covers the `emg-platform-core`/`emg-persistence` foundation independent
   of any single Module 1–10 entry.
3. Reference architecture — `docs/architecture/reference/api/EMG-Enterprise-API-Architecture.md`
   and the v2.0 Enterprise Intelligence Platform document tag API groups
   `M01`–`Mxx` (observed: M02, M04, M05, M06, M09, M10, M12, M13, M16, M17,
   M18), which does not map 1:1 to scheme 1 (e.g., scheme 3's M18 = Audit
   APIs, while scheme 1's Module 6 = Audit).

**Required future decision:** create a single canonical numbering model, or
an explicit, published mapping table between all three, so that a reference
to "Module 6," "M06," and "Phase 2" cannot be mistaken for describing the
same or different things without checking source.

**Status of dependent work:** `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`
§0 provides a working, non-authoritative reconciliation table so that
document could be written without waiting on this decision — that
reconciliation is scoped to Phase 3 only and does not substitute for a
platform-wide canonical decision.

**No implementation is blocked by this item** — it is a documentation-
governance risk, not a code dependency.

### D-A-002 — Entity Resolution Ownership

**Current state:** `libs/python/emg-entity-resolution` is a scaffolded
package with a 0-byte `pyproject.toml` and zero lines of source
(`IMPLEMENTATION_GAP_ANALYSIS.md` §2, Gap 1). `emg-memory-graph` already
contains its own, separately-built "Entity Resolution Engine
(deterministic)" as part of its existing, completed scope.

**Questions to resolve:**

- Is entity resolution meant to be a **standalone service**, independent of
  any single library?
- Is it meant to be **part of `emg-memory-graph`** — i.e., is
  `emg-entity-resolution` an abandoned or premature scaffold that should be
  removed once `emg-memory-graph`'s resolver is confirmed as the single
  implementation?
- Should it become a **shared library** that `emg-memory-graph`'s resolver
  is later extracted into, so that other future consumers (e.g., connector-
  sourced cross-system entity matching, as `emg-connectors` integrations
  mature) can use the same resolution logic without depending on the whole
  of `emg-memory-graph`?

**Binding constraint on future work:** no implementation may depend on
`emg-entity-resolution` until this ownership question is explicitly
approved. This applies to `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md`'s
Recommended Implementation Sequence (§10, step 6) and any future Knowledge
Graph Expansion (§8) or Knowledge Ingestion (ADR-020) work that might
otherwise be tempted to reference the empty package.

**2026-07-27 repository-integrity repair (does not resolve this decision):**
an independent architecture audit flagged that `tools/scripts/install-libs.sh`
was silently editable-installing this 0-byte-`pyproject.toml` scaffold
alongside the 17 real libraries on every `make bootstrap` (it built as an
empty, unowned `emg_entity_resolution-0.0.0` package rather than failing
loudly). `install-libs.sh` was updated to skip any library directory with an
empty/whitespace-only `pyproject.toml`, so this scaffold is no longer
installed. This is a bootstrap-hygiene fix only — the package, its
`docker/dependencies.yaml` manifest entry, and this Open decision are all
otherwise untouched; none of the three ownership questions above have been
answered. See `docs/devops/DEPENDENCY_GOVERNANCE.md` for the fix detail.

### D-A-004 — ADR-027 Stage 4 Phases 4B–4E Scope Definition

**Current state:** Resolved by the Architecture Board on 2026-08-01 against
baseline `develop` `9588c6d`. ADR-027 Revision 5 Stage 4 Phase 4A was
implemented at commit `08949e0`, reconciled at `f59cb4b` and `0ea7c74`, and
merged to `develop` at `aefc82c`. Phase 4B was implemented at commit
`c6c28bb` and merged through PR #45 at merge commit `6536b73`. Phase 4E has
completed the documentation-only governance and conformance closure, and
ADR-027 Revision 5 Stage 4 is complete.

**Owner:** Chief Data Officer (accountable owner, Module 7, ADR-016 §1).

**Approving authority:** Architecture Board.

**Decision date:** 2026-08-01.

**Resolution:**

- **Phase 4B — Approved and implemented.** Mutation-path observability
  emission only, implemented at `c6c28bb` and merged through PR #45 at
  `6536b73`:
  `mutation_requests_total`, `mutation_latency_seconds`,
  `idempotency_hits_total`, `authorization_denials_total`, and completion of
  safe structured-log fields at the mutation boundary. Excluded: any new
  route, any new command, any DTO change, payload or classification content
  in metric labels, a metrics backend, dashboards, alerts, a tracing
  collector, and production-readiness work.
- **Phase 4C — Closed as not required.** A batch mutation HTTP route is
  rejected for the current Stage 4 scope. The five-route ADR-027 Revision 5
  transport surface remains authoritative and complete. Batch semantics at
  ADR-027 §11.1 and §10.5 remain accepted and unexposed. Any future batch
  transport requires a new Board decision and ADR-027 Revision 6.
- **Phase 4D — Closed as not required.** Deployment documentation and
  rollout remain ADR-027 Stage 5. IaC, secrets management, observability
  backends, HA/DR, dashboards, and alerting remain in the
  production-readiness track.
- **Phase 4E — Complete.** Stage 4 governance and conformance closure;
  documentation and register reconciliation only, with no new capability.

The complete Stage 4 evidence and D-A-004 conformance mapping are recorded in
`docs/specifications/ADR-027/ADR-027_STAGE4_CLOSURE_RECORD.md`.

**Confirmed boundaries:**

- ADR-027 Phase 4B owns mutation-metric **emission**; ADR-015 / FEAT-12-3
  owns collection, storage, dashboards, tracing, and alerting.
- No user-interface work is authorized in ADR-027 Stage 4.
- T-A-002 (schema discovery) and T-A-003 (durable effective-schema-version
  recording) remain outside Stage 4 and retain their existing blocking
  authorities.
- ADR-033 Revision 2 Phase 4 remains a separate schema-registry track and is
  not ADR-027 Phase 4B.

**Binding constraint on future work:** phase labels and sequencing alone do
not authorize implementation. No route, command, DTO semantic, domain,
persistence, ledger, GraphStore, authorization-policy, or schema capability
may be inferred beyond the scope recorded above. This resolution creates no
ADR and amends no accepted ADR.

**Status:** Accepted.

---

## Observations

Observations are short, evidence-based findings that do not require a
binary accept/reject decision the way the Open Architecture Decisions above
do. They record what was found and a recommendation, and are closed when the
recommendation is actioned (or explicitly declined) — not left open-ended
like D-A-001, D-A-002, and D-A-004.

| ID | Title | Recommendation | Evidence |
| :--- | :--- | :--- | :--- |
| OBS-A-001 | Platform Core Dependency Direction Review | Accept current direction; fix a stale citation (pending); adjacent finding resolved via ECP-1 (2026-07-25); systemic detection gap closed via ECP-2 (2026-07-25) | See below |
| OBS-A-002 | Knowledge Graph Service Two-Package Structure | Accept as intentional, documented pattern (Actioned 2026-07-27) | See below |
| OBS-A-003 | ADR-025 Knowledge Graph Authorization Enforcement — implementation-time findings | Accept both fixes as-implemented; registry-allow-list gap remains open (follow-up, not blocking) (Actioned 2026-07-27) | See below |
| OBS-A-004 | ADR-026 Revision 2 Knowledge Graph Classification Enforcement — Phase 2 (D7–D13) completion record | Accept ADR-026 Revision 2 as fully implemented (Phase 1 + Phase 2); adopt Appendix ADR-026A's three principles as the standing rule for future `required_resource_attributes` reuse (Actioned 2026-07-27) | See below |
| OBS-A-005 | ADR-027 Revision 5 §5.3 and ADR-025 §11 compose correctly — human-only mutation sequencing | Record as an implementation sequencing observation; no architecture change, no ADR modification, no new decision (2026-08-01) | See below |

### OBS-A-001 — Platform Core Dependency Direction Review

**Trigger:** flagged in `IMPLEMENTATION_GAP_ANALYSIS.md` §4 (T-A-001 work) as
"reads architecturally backwards" — that characterization was made from
`pyproject.toml` alone, without reading the actual source. This observation
corrects and supersedes that earlier, under-evidenced flag.

**1. Current dependency direction (verified from source, not just
`pyproject.toml`):**

`emg-platform-core` → `emg-memory-graph`, one-directional, confirmed by:

- `emg_platform_core/ports/graph_store.py:25` — `from emg_memory_graph import
  MemoryGraph`. The `GraphStore`/`GraphTransaction` `Protocol`s are typed
  directly in terms of `MemoryGraph`: `read() -> MemoryGraph`,
  `write(..., graph: MemoryGraph, ...)`, `stage(graph: MemoryGraph)`.
- `emg_platform_core/adapters/in_memory.py:28` — `from emg_memory_graph import
  EMPTY_GRAPH, MemoryGraph`, used as the concrete in-memory representation
  backing `InMemoryGraphStore`.
- Confirmed **not circular**: `emg-memory-graph`'s own source has zero
  references to `emg_platform_core`.

**2. Whether this violates the intended layering model: No.**

`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9 ("Domain Model") explicitly names
the Memory Graph as *"the core"* bounded context (§10, item 3: "Memory Graph
— nodes, edges, evidence, temporal, versioning, lineage (**the core**)"),
and §11 ("Service Boundaries") states the "one writer per store" rule that
`ports/graph_store.py`'s own docstring cites verbatim. A storage port
(`GraphStore`) being expressed in terms of the domain aggregate it persists
(`MemoryGraph`) is the standard Repository-pattern shape in DDD/hexagonal
architecture — it is not a "core has zero dependencies" violation, because
the Freeze does not define `emg-platform-core` as a dependency-free package;
it defines it as the **storage-independence seam**, which by construction
must speak the domain's snapshot type. The earlier "reads backwards"
characterization was a naming-expectation mismatch (the word "core"/
"foundation" suggesting zero dependencies), not an actual Freeze violation.

**Citation discrepancy found (minor, documentation-only):**
`ports/graph_store.py`'s docstring and `emg-platform-core`'s `pyproject.toml`
description both cite "Freeze §32," but `EMG_PRODUCT_ARCHITECTURE_FREEZE.md`
has only 26 numbered sections plus a "Freeze Control" section — §32 does not
exist in the current document. §9 and §11 (also cited) do exist and do
substantively support the design, as shown above. This stale citation should
be corrected to reference an existing section (or removed) — a one-line
documentation fix, not an architecture question.

**3. Possible remediation options (for the citation issue and the
naming-expectation tension; not for a real defect, since none was found):**

- **Option A — Accept as-is, fix the citation (recommended).** Correct the
  dangling "§32" reference in `ports/graph_store.py` and `pyproject.toml` to
  cite §9/§11 only (both of which are already accurate). No structural
  change. Lowest risk, matches frozen architecture as written.
- **Option B — Clarify `emg-platform-core`'s package description** to state
  explicitly that it is "a storage-independence seam built on the
  `emg-memory-graph` domain snapshot type," not a zero-dependency foundation,
  preventing future readers from making the same under-evidenced "backwards"
  assumption this observation had to correct. Low risk, documentation-only.
- **Option C — Split `emg-platform-core` into a dependency-free ports-only
  package plus a separate in-memory-adapter package.** Would restore the
  conventional "core has no outward dependencies" shape, but is a real
  package split affecting every current and future consumer (`emg-persistence`,
  and anything Phase 3 builds against `GraphStore`) for a problem that is
  presently a naming concern, not a functional one. Not recommended unless a
  concrete future need for a dependency-free port package emerges.

**4. Risk level: Low**, for the platform-core/memory-graph direction itself
— deliberate, non-circular, frozen-architecture-aligned.

**Adjacent finding — RESOLVED via ECP-1 (2026-07-25):** `emg-persistence`
directly imported `emg_memory_graph` in two files
(`emg_persistence/store.py:12`, `emg_persistence/neo4j/projection.py:19`) but
did **not** declare `emg-memory-graph` in its own `pyproject.toml`
dependencies (only `emg-platform-core` and `emg-errors`). This worked only
because `emg-platform-core` transitively pulled in `emg-memory-graph` — if
that transitive relationship ever changed, `emg-persistence` would have
broken at import time despite its own declared dependencies appearing
satisfied. A follow-up Principal Engineer architecture review confirmed via
a repo-wide undeclared-import scan that this was the only such case among
all 17 libraries and 2 services, and produced ECP-1 (approved) to fix it:
`emg-memory-graph` is now declared in `emg-persistence/pyproject.toml` and
its `docker/dependencies.yaml` entry. Verified: both dependency checks pass,
the repo-wide scan now reports zero undeclared imports repo-wide,
`emg-persistence`'s test suite is unchanged (156 passed / 26 skipped), and
`mypy --strict` is clean.

Note that neither `check_dependency_manifest.py` nor
`check_dependency_drift.py` would have caught this class of issue on its own
(they compare a package's own declared deps against the manifest; they do
not verify a package's source imports against its own `pyproject.toml`).

**ECP-2 — RESOLVED (2026-07-25):** `tools/ci/check_implicit_dependencies.py`
now closes this detection gap. It walks every package's source with Python's
`ast` module and compares actual `emg-*` imports against that package's own
`pyproject.toml`, distinguishing runtime imports (build-failing) from
`TYPE_CHECKING`-only imports (informational). Wired into
`.github/workflows/ci.yml`'s `dependency-validation` job alongside its own
unit test suite (`tools/ci/tests/test_check_implicit_dependencies.py`, 15
tests against synthetic fixtures plus a live-repo zero-findings regression
guard). Verified: 0 findings across all 20 manifest components (2 services +
18 libraries), `ruff`/`black`/pre-commit clean, existing
`check_dependency_manifest.py`/`check_dependency_drift.py` unaffected. Full
detail in `docs/devops/DEPENDENCY_GOVERNANCE.md` ("Implicit Dependency
Detection"). A recurrence of the `emg-persistence`-class gap will now be
caught automatically in CI rather than requiring a manual architecture
review. Note this does not close the *separate*, still-open stale-manifest-
entry direction (a dependency declared but no longer used) — see that doc's
Open Questions.

**5. Should this become an ADR or remain an implementation task?**
**Remains an implementation/documentation task — no ADR needed.** The
dependency direction is already authoritatively grounded in
`EMG_PRODUCT_ARCHITECTURE_FREEZE.md` §9/§11 (frozen); nothing here
introduces a new architectural decision requiring board-level review. The
only concrete action is Option A (fix the stale §32 citation), which is a
small documentation correction, not an ADR-worthy decision. The adjacent
`emg-persistence` finding, if pursued, would also be an implementation task
(add the missing declared dependency, and optionally extend the drift
checker), not an ADR.

**Status:** Partially actioned. The adjacent `emg-persistence` finding is
**Resolved** (ECP-1, 2026-07-25), and the systemic detection gap that let it
go undetected is **Resolved** (ECP-2, 2026-07-25). The stale "§32" citation
fix (Option A) remains pending — a small, textual-only follow-up, not yet
applied. The platform-core/memory-graph direction itself required no change
(Accepted as-is).

### OBS-A-002 — Knowledge Graph Service Two-Package Structure

**Trigger:** the Sprint 7.4 architecture review asked whether
`services/knowledge-graph` splitting its source into two top-level packages
under one `pyproject.toml` — `emg_knowledge_graph` (application layer:
orchestrator, DTOs, commands) and `emg_knowledge_graph_api` (transport layer:
FastAPI routers, schemas, DI wiring) — is a deviation from repository
convention that needs correcting, or an intentional, justifiable pattern.
This was resolved during the Sprint 7.4 review-fix pass (packaging
re-evaluation) and is recorded here, per the Knowledge Graph Integration
Closure implementation specification (Group A4), as the lightweight
governance record for that decision instead of a new ADR.

**1. Current state (verified from source):**

`services/knowledge-graph/pyproject.toml` declares
`packages = ["src/emg_knowledge_graph", "src/emg_knowledge_graph_api"]` — one
`pyproject.toml`, two importable packages. This differs from every
`libs/python/emg-*` library (each is exactly one package per
`pyproject.toml`) and from `services/audit` and `services/identity` (each
also one package per `pyproject.toml`).

**2. Why this is a deliberate divergence, not an oversight:**

- **Single consumer.** `emg_knowledge_graph_api` has exactly one caller —
  itself as a deployable ASGI app — and exists solely to expose
  `emg_knowledge_graph`'s `KnowledgeGraphApplication` over HTTP. No other
  service or library imports `emg_knowledge_graph_api`. Splitting it into a
  second, independently-versioned `pyproject.toml`/`docker/dependencies.yaml`
  entry would add packaging and dependency-governance overhead
  (`check_dependency_manifest.py`, `check_dependency_drift.py`, and
  `check_implicit_dependencies.py` would all need a second manifest entry)
  for a package that will only ever be depended on by the thing it already
  ships inside of.
- **Always co-deployed.** Unlike `libs/python/*` packages (each reusable
  across multiple services) or the identity/audit split (separate deployable
  processes with separate lifecycles), `emg_knowledge_graph_api` has no
  existence independent of the `knowledge-graph` service process — there is
  no scenario where one is deployed, versioned, or tested without the other.
- **Dependency-boundary test already enforces the layering.** The transport/
  application boundary this split exists to express (routers depend on the
  application layer's DTOs/orchestrator, never the reverse; no FastAPI/HTTP
  types leak into `emg_knowledge_graph`) is verified by an existing
  import-boundary test in the service's test suite, not by package
  separation — the two-package structure documents the boundary for readers,
  the test enforces it for CI.

**3. Recommendation: Accept as-is.** No repository-convention change and no
new ADR are required. The one-package-per-`pyproject.toml` shape used
elsewhere in the repo is a convention for independently-reusable or
independently-deployable units; `emg_knowledge_graph_api` is neither, so the
convention's rationale does not apply to it. Documented here, and in
`services/knowledge-graph/src/emg_knowledge_graph_api/__init__.py`'s module
docstring, so a future reader does not need to re-derive this reasoning from
first principles.

**4. Status:** **Actioned (2026-07-27).** No further follow-up required
unless a second consumer of `emg_knowledge_graph_api` emerges, at which point
this observation should be revisited (a second consumer would remove the
"single consumer" justification above).

### OBS-A-003 — ADR-025 Knowledge Graph Authorization Enforcement — implementation-time findings

**Trigger:** ADR-025 (Knowledge Graph Tenant & Authorization Model) was
approved and implemented in full the same day (2026-07-27, Knowledge Graph
Integration Closure Group C). Implementing §8 of that ADR against real code
surfaced two small, evidence-driven gaps that the design phase could not have
caught by document review alone (both are implementation-detail fixes, not
redesigns — neither changes any decision recorded in ADR-025 §8). Recorded
here as the lightweight governance record for those findings, per the same
convention OBS-A-002 established, rather than a new ADR.

**1. `ServicePrincipal.service_name` — missing field, not a new capability.**
`emg_auth_client.ServicePrincipalLike` (the structural Protocol
`AuthorizationRequest.principal` is typed against) requires a `service_name`
field. `services/audit` and `services/identity`'s own `ServicePrincipal` types
already carry it; `services/knowledge-graph`'s did not — a pre-existing
Sprint 7.4 gap, never exercised before because nothing in that service called
into `emg_auth_client`/`emg_policy_engine` until ADR-025. Caught by
`mypy --strict`, not by design review. **Fix:** added `service_name: str = ""`
to `emg_knowledge_graph_api.authn.ServicePrincipal`, defaulting to empty
rather than a resolved registry value (see finding 2 below for why no
registry exists to resolve it from). **Accepted as-implemented** — narrowly
scoped to the HTTP layer already in Group C's scope, does not touch any
DO-NOT-MODIFY surface (Query Engine, `GraphStore`, persistence, Neo4j).

**2. Role-catalog review (ADR-025 §8.7 item 5 / Group C8) — no new role added,
but a related, still-open gap flagged.** `emg_policy_engine.roles.
ROLE_CATALOG`'s existing eight roles were reviewed against the Knowledge
Graph's caller population; no gap was found and no role was added.
`config/policy.example.yaml` grants `investigator`, `decision-maker`,
`knowledge-steward` (human) and `service-account` (machine) — deliberately
excluding the baseline `platform-user` role, which has no job-function tie to
graph-query access. Separately, and **not resolved** by this ADR: no service
client is registered anywhere (`identity`'s `SERVICE_REGISTRY`, the Keycloak
realm seed, or an equivalent) specifically as a Knowledge Graph API consumer,
and `emg_knowledge_graph_api.authn.TenantServiceTokenValidator` performs no
registry-based allow-list check on inbound `client_id`s at all — unlike
`services/audit`'s `_RECOGNIZED_CLIENTS` or `services/identity`'s
`SERVICE_REGISTRY`. Any validly-signed token for the configured realm/audience
is accepted; granting a role such as `service-account` in the policy file
therefore authorizes *any* service holding that realm role, not a specifically
reviewed Knowledge Graph consumer.

**3. Status: Actioned (2026-07-27).** Both fixes are implemented, tested
(`pytest`, `mypy --strict`, dependency-governance checks all green), and
documented in ADR-025 §18 and `services/knowledge-graph/README.md`'s
"Authorization" section ("Known limitation"). **The registry-allow-list gap
(finding 2's second half) remains open** as a follow-up task, out of Group
C's authorized scope — introducing such a registry (mirroring
`identity`/`audit`) is a candidate for a future, narrowly-scoped
implementation task, not a new ADR (the mechanism already exists elsewhere in
the repo; this is a reuse/extension, not a new design decision).

---

### OBS-A-004 — ADR-026 Revision 2 Knowledge Graph Classification Enforcement — Phase 2 (D7–D13) completion record

**Trigger:** ADR-026 Revision 2 (Knowledge Graph Classification Enforcement
Model) was approved with Phase 1 (D1–D6, plus the Part F remediation) and
Phase 2 (D7–D13) delivered as a sequence of independently-reviewed batches:
Batch 1 (D7 DTO projection + D8 the `classification.py` HTTP adapter),
Batch 2 (D9 route wiring + D10 deployment docs, followed by a remediation
of two findings from independent verification), and Batch 3 (D11 full test
suite + D12 boundary verification + D13, this record). All three batches
are now complete; this entry is the governance record D13 requires.

**1. What is now fully implemented, end-to-end.** All seven Knowledge Graph
Query API routes enforce classification per returned object, via a second
`PolicyEnforcementPoint.authorize()` call (identical mechanism to ADR-025's
existing operation-level check, never a second engine), using
`resource_attributes={"classification": <object>.classification.value}`.
`emg_knowledge_graph_api.classification` is the sole place this decision is
applied at the HTTP layer; every route calls exactly one of its
`filter_*`/`gate_*` functions and applies the result using its own
pre-existing not-found/empty/no-value shape (ADR-026 Revision 2 §8.5's
uniform denial principle) — never a new error type or status code.
`config/policy.example.yaml` (Group D6, authored in Phase 1) is the real,
enumerated policy data exercised end-to-end for the first time in Group
D11's test suite (`services/knowledge-graph/tests/api/
test_classification_scenarios.py`): dominance-boundary tests across all
four clearance tiers, per-endpoint pruning, shortest-path and history
blocking, `get_entity`/`get_edge` 404-on-denial, the default-`UNCLASSIFIED`
path, and a regression test confirming ADR-025's 403 still fires before any
classification logic runs.

**2. Two audited findings during Phase 2, both remediated (not a new
decision — implementation-detail fixes against ADR-026 Revision 2's own
§8.5 uniform-denial principle).**

- **Pagination metadata leak.** The first Batch 2 delivery derived
  `has_more`/`next_cursor` from the raw, unfiltered application-layer page,
  which could let a client infer a hidden classified object's existence
  (most directly: `next_cursor` could literally be a denied object's own
  id). **Fixed:** the three paginated routes now perform HTTP-layer
  look-ahead (`_authorized_page` in `routers/knowledge_graph.py`),
  re-deriving `returned_count`/`has_more`/`next_cursor` entirely from the
  authorized (post-filter) item set — still calling only the existing
  `PolicyEnforcementPoint`/`classification.filter_*` functions, no
  comparison or ranking logic added.
- **Denied-history classification leak.** `classification.
  gate_history_fact` preserved the real `classification` value on a denied
  `EntityHistoryResult` even though `item` was cleared to `None`. **Fixed:**
  `EntityHistoryResult.classification` is now `Classification | None`, and
  the denied branch sets it to `None` too — the true value is used
  internally to make the one decision it exists for, and is never handed
  back once that decision is "deny". (Independent verification at the time
  found the HTTP response body itself never serialized this field either
  way — `mapping.py`/`schemas.py` have no `classification` field on
  `EntityHistoryResultResponse` — but the DTO-level fix closes the gap at
  its source rather than relying solely on the mapping layer never
  changing.)

Both fixes were regression-tested (6 required categories: empty filtered
page, `has_more` non-leak, `next_cursor` non-leak, pagination metadata
authorized-only, denied history never serializing classification, denied
history indistinguishable from the pre-existing no-value response) and are
covered by `services/knowledge-graph/tests/api/test_classification_wiring.py`.

**3. Boundary verification (Group D12), now an executable guarantee.**
`services/knowledge-graph/tests/test_dependency_boundary.py` gained two new
tests confirming `emg_knowledge_graph` (the Query Engine/domain layer)
imports neither `emg_auth_client` nor `emg_policy_engine`, and declares none
of `Principal`/`ServicePrincipal`/`PolicyEngine`/`PolicyRule`/
`PolicyEnforcementPoint`/`AuthorizationRequest`/`Decision` as a type name —
i.e. the D7 `results.py` field additions (classification *data* only)
introduced no principal/authorization concept into the domain package.
`libs/python/emg-policy-engine/tests/test_no_scripting_capability.py` (new)
confirms `PolicyRule`'s field set is unchanged from Amendment 1 and that no
`eval`/`exec`/`compile` call or ranking/dominance-comparator function exists
anywhere in `emg_policy_engine`'s source. All pre-existing boundary tests
continue to pass unmodified.

**4. Standing rule adopted (D13's second requirement): Appendix ADR-026A's
three governing principles, as recorded in
`docs/architecture/EMG_ADR-026_KNOWLEDGE_GRAPH_CLASSIFICATION_ENFORCEMENT_MODEL.md`,
apply to *any future* reuse of `required_resource_attributes` — not only
classification — and are adopted here as a standing architectural rule,
not a one-time exception for this ADR:**

1. The Policy Engine remains a purely declarative, allow-list/all-of
   matching schema. `required_resource_attributes` (or any future
   resource-attribute-conditioned field) must never become an expression
   language, a scripting hook, or gain an ordinal/ranking comparison
   primitive — an ordinal concept (such as classification dominance) is
   always expressed as enumerated policy data (one rule per satisfying
   combination), never as new code in `PolicyRule`/`PolicyEngine`.
2. `required_resource_attributes` stays symmetric with `required_attributes`
   in shape and evaluation (all-of, matched against an allow-list); no
   parallel or special-cased policy model is introduced for a new
   resource-attribute use case, and the engine itself never special-cases
   any specific attribute name (e.g. `"classification"`) — the same generic
   matching logic must serve every future attribute unchanged.
3. Any future resource-attribute-conditioned concept (need-to-know,
   compartments, data residency, or similar) requires its own, independent
   ADR before being wired into live enforcement — this reuse pattern being
   easy to repeat is not itself authorization to repeat it without review.

**5. Status: Actioned (2026-07-27).** ADR-026 Revision 2 is recorded as
fully implemented (Phase 1 + Phase 2). Full `pytest`/`ruff`/`black`/
`mypy --strict`/dependency-governance validation passed repo-wide for every
batch, including this one. No code was committed as part of this
documentation-only update.

---

### OBS-A-005 — ADR-027 Revision 5 §5.3 and ADR-025 §11 compose correctly — human-only mutation sequencing

**Trigger:** An independent Architecture Board review asked whether
ADR-027 Revision 5's authorization of human callers contradicts ADR-025's
treatment of the human Knowledge Graph authentication path as future work.

**Finding:** The two accepted ADRs compose correctly. ADR-027 Revision 5
§5.3 restricts Restore, Merge, and Reclassify to
`required_roles=["knowledge-steward"]`. ADR-025 §8.9 records the human
`Principal` login path for the Knowledge Graph API as a reserved extension
point not implemented by that ADR, and notes that
`AuthorizationRequest.principal` is already typed generically so that adding
a human path later requires no change to its authorization call site.

**Repository-verified behaviour:** the three human-only mutation operations
are intentionally unreachable for the service callers that exist today.
`services/knowledge-graph/tests/test_authz_scenarios.py` asserts an
`expected_outcome="deny"` for the writer Service Principal against
`knowledge-graph.entity` `restore`, `merge`, and `reclassify`. This
observation records only that tested behaviour.

**Sequencing:** human authentication for the Knowledge Graph API remains
future work under ADR-025 §8.9.

**Status: Observation only (2026-08-01).** This is an implementation
sequencing observation. It records no architecture change, modifies no ADR,
and creates no new decision. No code, test, schema, or configuration was
changed to produce it.

---

## Tracked Architecture Tasks

| ID | Task | Status | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| T-A-001 | Extend dependency manifest coverage to all EMG Python components | **Done (2026-07-25)** | See below |
| T-A-002 | Ratify the supported-schema discovery transport contract | **Open** | A named owner and governance authority approve the URI, authentication model, response DTO, and transport acceptance criteria before any standalone discovery endpoint is implemented |
| T-A-003 | Assign and ratify durable effective-schema-version audit recording | **Open** | A named owner and target ADR (an ADR-030 revision or a separate ADR) are assigned, and the durable-recording and migration contract is approved before any persistence or ledger change |

### T-A-001 — Extend dependency manifest coverage to all EMG Python components

**Original state:** `docker/dependencies.yaml` declared 5 of 25 total
components (18 libraries + 7 services) — `identity`, `audit`, `persistence`,
`memory-graph`, `entity-resolution`
(`IMPLEMENTATION_GAP_ANALYSIS.md` §4, Gap 2; `docs/devops/DEPENDENCY_GOVERNANCE.md`
Constraints).

**Acceptance criteria (status):**

- ✅ Every `libs/python/*` package is represented in
  `docker/dependencies.yaml` — all 18 libraries now have an entry, each
  populated from its own `pyproject.toml`'s actual declared `emg-*`
  dependencies.
- 🟡 Every service's Dockerfile dependencies are validated by
  `tools/ci/check_dependency_manifest.py` against its manifest entry — true
  for the two services that have a Dockerfile (`identity`, `audit`); the
  other five services (`authz`, `knowledge-graph`, `retrieval`,
  `ai-orchestration`, `decision-intelligence`) remain scaffolded with no
  Dockerfile, so there is nothing yet for this criterion to check for them.
  This criterion will re-apply automatically as each is implemented.
- ✅ CI (`.github/workflows/ci.yml`, `dependency-validation` job) fails the
  build on dependency drift for every represented component — verified: both
  `check_dependency_manifest.py` and `check_dependency_drift.py` now run
  against all 20 declared entries (2 services + 18 libraries) and pass
  cleanly.

**Also fixed as part of this task:** `check_dependency_manifest.py` was
hardened with the same missing-`services`-key guard
`check_dependency_drift.py` already had (raised a raw `KeyError` otherwise).

**Anomaly discovered, not resolved:** `emg-platform-core`'s `pyproject.toml`
declares `emg-memory-graph` as a dependency, which reads architecturally
backwards for a foundation package. Recorded in
`IMPLEMENTATION_GAP_ANALYSIS.md` §4 as a flagged observation, not decided
here — it did not block completing this task since the manifest reflects
declared reality rather than an idealized dependency direction.

**Sequencing:** this was implementation-sequence step 1
(`PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10) — complete before any new
Phase 3 service is scaffolded, so drift detection covers new work from day
one.

### T-A-002 — Ratify the supported-schema discovery transport contract

**Current state:** ADR-032 §2.3 requires the server to publish its
authoritative supported schema-version set, and ADR-033 Revision 2 §10.4
requires a discovery surface exposing supported versions, lifecycle state,
retirement instants, and the recommended current version. The Phase 4
Design Package clarifies that mutation-request negotiation is live but is
not a standalone discovery endpoint. Its §4 records the discovery URI,
authentication model, and response DTO as unratified and therefore
governance-blocked.

**Owner:** TBD.

**Evidence:**

- `docs/architecture/EMG_ADR-032_KNOWLEDGE_GRAPH_SCHEMA_VERSIONING_AND_EVOLUTION.md`
  §2.3.
- `docs/architecture/EMG_ADR-033_SCHEMA_REGISTRY_AND_NEGOTIATION_SERVICE.md`
  §10.4.
- `docs/specifications/ADR-033/Phase4-Design-Package.md` §§4 and 13.

**Blocking questions:** What URI and method expose discovery? What
authentication and visibility rules apply? What closed response DTO
represents supported versions, lifecycle states, retirement instants, and
the recommended version? What public error and OpenAPI contract applies?

**Acceptance criteria:** a named owner and governance authority approve the
complete transport contract and its acceptance evidence before
implementation begins.

**Binding constraint:** no standalone discovery route may be added while
this task is Open. Existing schema negotiation on approved mutation
requests remains unchanged and must not be represented as the discovery
surface.

**Status:** Open.

### T-A-003 — Assign and ratify durable effective-schema-version audit recording

**Current state:** ADR-032 §2.4 requires the effective schema version in all
audit records. ADR-033 Revision 2 §10.3 confirms that the accepted contract
version currently terminates at the HTTP response header and is exposed
only through health, metrics, and structured logs; it is not persisted in
the mutation ledger, idempotency index, or another durable store.
`command_schema_version` is the distinct internal command-envelope version
and must not be repurposed. ADR-033 records this unmet requirement as OG-1
and its binding condition C2 requires assignment of an owner and target ADR.

**Owner:** TBD.

**Evidence:**

- `docs/architecture/EMG_ADR-032_KNOWLEDGE_GRAPH_SCHEMA_VERSIONING_AND_EVOLUTION.md`
  §2.4.
- `docs/architecture/EMG_ADR-033_SCHEMA_REGISTRY_AND_NEGOTIATION_SERVICE.md`
  §10.3, §15 OG-1, and binding condition C2.
- `docs/architecture/EMG_ADR-030_MUTATION_LEDGER_ATOMIC_IDEMPOTENCY.md`
  §5.1.

**Blocking questions:** Who owns OG-1? Will its contract be governed by an
ADR-030 revision or a separate ADR? Which durable audit records carry the
accepted schema version, and what atomicity, immutability, replay, migration,
retention, and backfill semantics apply?

**Acceptance criteria:** a named owner and target ADR (an ADR-030 revision
or a separate ADR) are assigned, and the durable record shape, transaction
boundary, migration strategy, replay behavior, and acceptance evidence are
approved before implementation begins.

**Binding constraint:** no ledger column, persistence behavior, migration,
fingerprint input, replay semantic, or `command_schema_version` meaning may
change while this task is Open. This entry tracks ADR-033 OG-1; it does not
resolve it or amend ADR-030.

**Status:** Open.

---

## Approved Implementation Sequence (Reference)

For traceability, the sequence approved alongside this register (no code
changes made in this documentation pass):

1. Extend dependency manifest coverage (T-A-001, above).
2. Add `LanguageCode`/`Locale` to `emg-common-types`.
3. Build `services/knowledge-graph`.
4. Build Enterprise API Gateway.
5. Build AI Orchestration service (`services/ai-orchestration`).
6. Build Administration service (`services/administration`, to be
   scaffolded).
7. Resolve entity-resolution ownership (D-A-002, above) before any
   integration depends on it.

This sequence is recorded here as the currently-approved plan; it is
detailed in full in `PHASE3_ENTERPRISE_PLATFORM_ARCHITECTURE.md` §10.
