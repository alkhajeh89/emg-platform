# EMG Production Readiness Roadmap

Date: 2026-07-27
Baseline: `adr-026-complete` (commit `5028aa5`)
Protocol: `docs/architecture/PROMPT_TEMPLATE_POST_ADR026.md`
Scope: Architecture-only gap assessment. No code was written or modified to
produce this document.

This document is a point-in-time audit of the EMG repository against its own
architecture baseline (`ARCHITECTURE_STATUS.md`, `EMG_ARCHITECTURE_DECISION_REGISTER.md`,
the Engineering Backlog, and the security/technical-debt registers), aimed at
answering one question: **what stands between the current repository state
and a first production-ready release, and in what order should it be closed?**

## Governance Reconciliation Addendum — 2026-08-01

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

## Persistence Reconciliation Addendum — 2026-08-03

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
  **Draft — not Accepted, `Decision Date: TBD`**. Its decisions are unchanged by
  this addendum. The underlying readiness finding stands: **no consumer of the
  `mutation_dispatch` `audit` channel exists**, so cross-service audit
  reconciliation is still not delivered.

**New and unchanged open items:**

- **P-02 evidence ledger.** The `EvidenceLedgerRepository` is implemented
  (PR #55) under an accepted contract that authorized the repository contract
  **only**. There is no ingestion wiring, API, worker, UI, or product
  capability, and no production caller. Its EL-10 schema hardening — a
  database-enforced append-only trigger, `prev_hash NOT NULL`, `seq >= 1`, and
  hash-format checks — is **required before the ledger is relied upon as an
  evidentiary record** and is not yet applied.
- **TD-002** (continuous `ProjectionWorker` daemon) remains open and accepted.
- Backup, restore, PITR, and disaster-recovery procedure remain unspecified.

Current persistence detail: `docs/engineering/persistence-architecture.md` and
`docs/engineering/persistence-operations.md`.

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
| 6 (Audit) | Frozen | Complete (EPIC-04, FEAT-04-1→4) | Clearance-based classification-aware *read authorization* remains filter-only, not enforced (see §4) |
| 7 (Knowledge Graph) | Frozen | Query API and ADR-027 Revision 5's five-route mutation API are live and authorization- and classification-enforced through Stage 4 Phase 4A | The ADR-027 write-path decision is closed. The separate library-first ingestion pipeline (`emg-knowledge-pipeline`), trust scoring, semantic layer, and lifecycle library remain unwired to a live service path, and the Neo4j serving-projection binding remains open. |
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
| ADR-028 | Audit reconciliation | **Referenced, not written, not begun** | Re-verified at `aefc82c`; status unchanged. Blocks any cross-service audit-integrity guarantee beyond single-service append-only logs. |

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
- **D-A-004 — ADR-027 Stage 4 Phase 4B–4E Scope Definition.** Phase 4A is
  complete; the objectives and acceptance criteria for later ADR-027 delivery
  phases have not been approved. This open decision blocks work from being
  labeled Phase 4B–4E, but it does **not** reopen the accepted write-path
  decision or Phase 4A completion.

---

## 4. Known Security Limitations (production-blocking subset)

Pulled from `docs/engineering/security-limitations.md` and the ADR-025/026
governance records — limited here to items that matter for a *production*
release, not every documented scope boundary:

1. **Audit clearance-based read authorization is filter-only, not enforced.**
   FEAT-04-4 documents this explicitly: "Classification *filtering* ships in
   FEAT-04-4; classification *enforcement* does not." This is the same class
   of gap ADR-026 just closed for the Knowledge Graph — it has not been
   closed for the Audit service's own query endpoints.
2. **No registry-based allow-list of Knowledge Graph API service clients**
   (OBS-A-003, finding 2, still open). Any validly-signed token for the
   configured realm/audience is accepted by
   `emg_knowledge_graph_api.authn.TenantServiceTokenValidator` — unlike
   `services/audit`'s `_RECOGNIZED_CLIENTS` or `services/identity`'s
   `SERVICE_REGISTRY`. A specific service holding a granted role is not the
   same guarantee as a specifically reviewed Knowledge Graph consumer.
3. **`/authz/check` (identity service) is introspection, not enforcement** —
   by deliberate design, but worth restating for release planning: it is not
   a substitute for a real PEP gate on any resource, and no resource server
   besides `services/knowledge-graph` currently calls the PEP for
   enforcement.
4. **No security scanning in CI.** `.github/workflows/ci.yml` runs lint,
   type-check, dependency-governance, and persistence-integration jobs —
   **zero** SAST, DAST, dependency/SCA vulnerability scanning, secret
   scanning, or container/IaC scanning. This is FEAT-12-2 (Security Scanning
   Suite), not started.
5. **No production secrets management.** Every secret in the repository
   (`docker-compose.yml`, Keycloak realm seed, service `Settings` defaults)
   is an explicitly labeled local-development placeholder. FEAT-11-3
   (Secrets Management) is not started; there is no centralized,
   least-privilege secrets store integration anywhere in the codebase.

---

## 5. Infrastructure & Operability Gap (EPIC-11 / EPIC-12)

This is the largest single gap for a *production* release, distinct from
feature completeness:

- `infra/kubernetes/`, `infra/modules/`, and every `infra/environments/*/`
  directory contain **only `.gitkeep` and a `README.md`** — no Terraform, no
  Kubernetes manifests, no Helm charts, nothing deployable beyond the local
  `docker-compose.yml`. FEAT-11-1 (Cluster Provisioning) and FEAT-11-2
  (Infrastructure-as-Code Baseline) have not started.
- FEAT-11-3 (Secrets Management), FEAT-11-4 (Capacity & HA/DR
  implementation of ADR-017), and FEAT-11-5 (Air-Gapped Deployment
  Packaging) have not started.
- FEAT-12-1 (full staged CI/CD pipeline) is partially present — a single
  `ci.yml` with lint/typecheck/dependency-governance/persistence-integration
  jobs — but there is no deployment pipeline, no environment promotion, no
  progressive delivery.
- FEAT-12-3 (Observability Platform: logs/metrics/traces per ADR-015) is
  represented only by `emg-telemetry` (149 lines — correlation-id and
  structured-log plumbing). There is no metrics backend, no distributed
  tracing, no dashboard, and no alerting (FEAT-12-4).
- FEAT-12-5 (Release & Rollback Automation) has not started.

**No production release can ship without at least FEAT-11-1/11-2/11-3 and
FEAT-12-2/12-3 in some minimal form** — this is an operational floor, not a
feature-richness question, and it is currently entirely unaddressed.

---

## 6. Technical Debt (from `docs/engineering/technical-debt.md`)

| ID | Item | Severity | Status |
| --- | --- | --- | --- |
| TD-001 | `mypy --strict` not enforced in CI | Low | **Resolved** (Phase 1) |
| TD-002 | No continuous `ProjectionWorker` daemon | Low | Open, accepted — fine for current read-repair model, but relevant once near-real-time projection freshness is needed |
| TD-003 | `neo4j/lazy.py` driver-construction path lacks unit coverage | Low | Open, accepted |
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
4. Fix the stale `services/knowledge-graph/service.yaml` comment, which
   still states "no classification-based access control" — this is now
   false as of ADR-026 and will mislead the next reader.
5. Apply OBS-A-001's still-pending Option A (fix the dangling "§32"
   citation in `ports/graph_store.py` / `emg-platform-core`'s
   `pyproject.toml`).

### Phase 1 — Close the two known live-security gaps before adding new surface area

6. **Audit clearance-based read authorization** (§4, item 1) — extend the
   same PEP/Policy Engine pattern ADR-026 just proved for Knowledge Graph to
   the Audit query endpoints. This is a reuse of an existing, approved
   mechanism (per ADR-026A's own standing rule), likely a short ADR plus a
   small implementation batch — not a new authorization design.
7. **Knowledge Graph service-client registry allow-list** (§4, item 2) —
   mirror `identity.SERVICE_REGISTRY` / `audit._RECOGNIZED_CLIENTS`. Small,
   scoped, no new ADR needed (the mechanism already exists elsewhere in the
   repo).

### Phase 2 — ADR-027 write-path decision closed; integration bindings remain open

8. **ADR-027 mutation write path — Closed.** ADR-027 Revision 5 is Accepted,
   and Stage 4 Phase 4A's five authenticated mutation routes and conformance
   requirements are complete on `develop` at `aefc82c` (PR #37). D-A-004
   tracks definition of Phase 4B–4E and does not reopen this decision.
9. **Complete the still-open population and serving bindings.** Wire the
   separate `emg-knowledge-pipeline` into an approved live service path and
   complete the Neo4j serving-projection binding. These are integration tasks
   that remain open after Phase 4A; they must not be represented as completed
   merely because the ADR-027 HTTP write surface is live.

### Phase 3 — Infrastructure & operability floor (EPIC-11/EPIC-12 minimum viable subset)

10. FEAT-11-2 (Infrastructure-as-Code baseline) + FEAT-11-1 (cluster
    provisioning) for at least one real target environment (staging is the
    natural first target given `infra/environments/staging/` already exists
    as a placeholder).
11. FEAT-11-3 (Secrets Management) — replace every local-dev placeholder
    secret path with a real centralized store integration before any
    non-local deployment.
12. FEAT-12-2 (Security Scanning Suite) — SAST/SCA/secret scanning are the
    highest-value-per-effort additions to `ci.yml`; container/IaC scanning
    can follow once Phase 3 infrastructure exists to scan.
13. FEAT-12-3 (Observability Platform, minimum: metrics + traces wired to a
    real backend, not just structured logs) and FEAT-12-4 (alerting/SLO).
14. FEAT-11-4 (Capacity & HA/DR) and FEAT-12-5 (Release & Rollback
    Automation) — needed before calling the release "production-ready" in
    the ADR-017 sense, but reasonably sequenced after the above since they
    depend on a real deployment target existing first.
15. FEAT-11-5 (Air-Gapped Deployment Packaging) — only if the first
    production release's target environment requires it; otherwise defer
    past v1 (this should be an explicit scoping decision, not an
    assumption).

### Phase 4 — Everything else in the frozen Backlog (post-v1 candidate)

Modules 8, 9, and 10 (Search/GraphRAG, AI Orchestration, Decision
Intelligence — EPIC-06 through EPIC-09) and the frontend (EPIC-10) have zero
implementation. Given the module-dependency gate and the fact that Modules
8–10 all consume the Knowledge Graph, **none of this should begin before
Phase 2's remaining population and serving bindings are implemented and
validated** —
the ADR-027 write-path decision is closed, but starting Search or AI
Orchestration while the ingestion-pipeline and Neo4j projection bindings are
still incomplete risks rework. This phase is listed for completeness, not as
part of the critical path to a first production-ready release, which this
document interprets as Identity + Audit + Knowledge Graph (with its write-path
decision resolved and its required bindings complete) running on real
infrastructure with a real security and observability floor.

---

## 8. Summary Table — What Blocks "First Production-Ready Release"

| Blocker | Category | Phase |
| --- | --- | --- |
| Module numbering / entity-resolution ownership unresolved | Governance | 0 |
| Audit classification read-authorization is filter-only | Security | 1 |
| No Knowledge Graph client registry allow-list | Security | 1 |
| ADR-027 write path decided and Phase 4A implemented; ingestion-pipeline and Neo4j serving bindings remain open | Integration implementation | 2 |
| No IaC / cluster provisioning beyond local docker-compose | Infrastructure | 3 |
| No centralized secrets management | Security / Infrastructure | 3 |
| No security scanning in CI | Security | 3 |
| No metrics/tracing backend or alerting | Observability | 3 |
| No HA/DR realization of ADR-017 | Infrastructure | 3 |
| No release/rollback automation | Infrastructure | 3 |
| Modules 8–10 fully unimplemented | Feature scope | 4 (post-v1) |

---

## 9. Remaining Risks

No known architectural violations were found — the frozen architecture
(PolicyEngine/PolicyEnforcementPoint boundaries, dependency direction,
fail-closed security posture) is consistently honored everywhere it has been
engineered. The risks that remain are scope and sequencing risks, not
architectural-integrity risks:

- The Knowledge Graph write-path decision is closed, but the open ingestion-
  pipeline and Neo4j serving-projection bindings (§7, Phase 2) remain the
  highest-leverage Module 7 integration risk for downstream modules 8–10 and
  the production-readiness timeline.
- Infrastructure/operability (EPIC-11/12) is a large, currently-zero body of
  work; underestimating its size relative to feature work is the most likely
  planning failure mode for a "first production release" target date.
- D-A-001/D-A-002 are low-risk individually but compound review overhead on
  every future ADR until resolved — recommended to close early precisely
  because they are cheap.
