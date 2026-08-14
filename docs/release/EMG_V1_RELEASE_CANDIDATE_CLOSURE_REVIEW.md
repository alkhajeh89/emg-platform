# EMG v1.0 Release Candidate Closure Review

> **Historical review.** This record captures the repository at commit `8556137`. RC-A through
> RC-F subsequently closed several repository gaps described below; do not treat this historical P0
> count as the current implementation inventory. `docs/release/EMG_V1_RC8_PARALLEL_COMPLETION_REVIEW.md`
> is the next historical checkpoint (RC.8, source commit `b3e6cc7`). For current repository status —
> including the since-committed ADR-043 Identity durable refresh-state/recovery-governance
> implementation and the rollback-version-chronology release-tooling fix, neither of which existed at
> RC.8 — use `docs/release/EMG_V1_RC9_PREPARATION_AND_CLAUDE_RECONCILIATION.md`.

**Review date:** 2026-08-11
**Branch:** `audit/release-candidate-closure`
**HEAD:** `8556137fd42dc840bda1c85fa1045c2bbd88dd12`
**Baseline:** refreshed `origin/develop` at the same commit
**Verdict:** **NOT READY**
**Production Readiness Score:** **69/100**

## 1. Executive conclusion

EMG has a well-tested core, strong authorization and persistence boundaries, governed search,
delegated human identity, an authoritative audit path, migration governance, production-oriented
service containers, and a serious image supply-chain workflow. It cannot yet legitimately be
declared “EMG Platform v1.0 — Production Ready.”

Five release blockers remain. Most importantly, the repository has no production image or
Kubernetes workload for the Studio frontend. The production ingress routes `/` to Studio BFF,
whose image contains only the Python API and does not serve the Next.js application. The current
repository-controlled production bundle therefore cannot deploy the product UI.

The other blockers are operational evidence gaps: no completed production environment/promotion
run, no provisioned alerting stack or alert rules, no witnessed production backup/restore
rehearsal, and no live end-to-end qualification of the required trust/data/recovery chains.
These are not cosmetic omissions and cannot be replaced by unit tests or documentation claims.

No contradiction was found in the authoritative persistence, authorization, classification,
delegation, or browser trust boundaries. No new ADR is required to begin closure work.

## 2. Ground truth and inventory

The branch and refreshed remote baseline are identical. The working tree was clean at review
start. Recent history ends with PR #86 (Studio Knowledge Graph Explorer), preceded by governed
search UI, BFF search, core search, and Studio expansion merges.

Repository runtime inventory:

- Applications: `apps/studio` and `apps/studio-bff`.
- Implemented services: Identity, Audit, Audit Projector, and Knowledge Graph. Other service
  directories such as AI orchestration, retrieval, decision intelligence, and authz are scaffolds
  or future capability and are not production runtimes.
- Python libraries: 18 governed `emg-*` packages covering persistence, policy, ontology,
  lifecycle, graph, audit, telemetry, connectors, and platform contracts.
- Persistence: PostgreSQL authoritative repositories, Neo4j projection, connection pooling,
  migration runner, outbox/dispatch, revision, mutation, evidence, and search repositories.
- Migrations: Audit V001; Knowledge Graph PostgreSQL V001–V010; Neo4j M001.
- Deployment: Kustomize base/production overlays, ExternalSecret templates, NetworkPolicies,
  migration/provisioning Jobs, backup tooling, and five service/deployment-tool images. There is
  no Studio frontend image or workload.
- CI/CD: `ci.yml` and tag-triggered `runtime-image-release.yml`.
- Dependency governance: hash-locked Python requirements, npm lockfile, dependency manifest,
  drift and implicit-import validators.
- Tests: 2,397 default pytest cases collected, Studio Vitest suite, real PostgreSQL/Neo4j CI job,
  provisioning and recovery test assets.

## 3. Architecture decision conformance

### Accepted and implemented

Repository code and tests substantively implement the decisions governing authoritative
PostgreSQL persistence and Neo4j projection, revision/mutation semantics, tenant authorization,
classification, mutation idempotency, schema evolution, service trust, human authentication,
Studio BFF, delegated identity, governed search, production provisioning, and runtime image
supply chain. Principal evidence includes:

- `emg-persistence` PostgreSQL stores, migrations, outbox, projection checkpoint/repair, and
  integration suites.
- Knowledge Graph authentication, PolicyEngine wiring, classification scenarios, bounded query
  contracts, delegated requests, atomic mutation, and governed-search tests.
- Studio BFF OIDC, secure-cookie, CSRF, logout, RFC 8693 delegation, restricted proxy, and startup
  validation tests.
- Audit/Audit Projector delivery, retry, custody/evidence, authoritative ledger integration, and
  projector provisioning tests.
- ADR-040 image inventory/release validator and ADR-041 production-provisioning validator.

### Accepted but operationally incomplete

- ADR-015 observability: structured observations exist, but no repository-provisioned metrics
  backend, dashboards, or production alert rules exist.
- ADR-039 backup/PITR: scripts, schema, CI rehearsal, and RPO/RTO documentation exist; production
  scheduler, KMS custody, remote retention, and witnessed restore evidence are environment-owned
  and absent.
- ADR-040 supply chain: workflow supports build-once, Trivy, SBOM, GHCR, Cosign and provenance;
  the documented first live release and protected environment evidence are absent, and Studio is
  outside the governed image inventory.
- ADR-041 provisioning: manifests and validation are implemented, but sequencing is manual/CD
  owned and no target-environment completion record exists.

### Proposed, superseded, or not required for v1 closure

ADRs 019–021 remain proposed and their AI orchestration, ingestion, and broader API ambitions are
not treated as v1 release commitments. Historical ADR-027 analysis/plan documents are not
authoritative over the accepted mutation decision and implemented revision. No accepted decision
was found to make the placeholder Decision, Evidence, or Timeline Studio routes mandatory for the
controlled RC, although presenting them as navigable product routes is a GA readiness gap.

## 4. Platform capability inventory

| Capability | Status | Direct repository evidence |
| --- | --- | --- |
| Identity/authentication | COMPLETE | Identity service, Keycloak client, token validators and tests |
| Human Studio sessions | COMPLETE | BFF OIDC/PKCE/session/logout/cookie tests |
| Service authentication | COMPLETE | service-token validators and production provisioning |
| Delegated human identity | COMPLETE | BFF exchange plus KG delegated-credential validation |
| Authorization | COMPLETE | PolicyEngine wiring and negative API scenarios |
| Classification enforcement | COMPLETE | canonical classification and scenario tests |
| Tenant isolation | COMPLETE | derived tenant context; no tenant query input |
| Memory Graph | COMPLETE | domain/query/projection suites |
| Ontology | COMPLETE | conformance and descriptor tests |
| Revision engine | COMPLETE | revision workflow/history/store suites |
| PostgreSQL authority | COMPLETE | PostgreSQL repositories and accepted architecture |
| Neo4j projection | COMPLETE | projection worker/checkpoint/hash/repair tests |
| Projection consistency/repair | COMPLETE | stale/corruption and replay coverage |
| Transactional outbox | COMPLETE | outbox/mutation ledger repositories and tests |
| Mutation dispatch | COMPLETE | projector worker, retry/backlog/idempotency tests |
| Audit service | COMPLETE | authenticated API, append/custody/reporting tests |
| Audit Projector | COMPLETE | runtime, delivery, worker and integration tests |
| Audit evidence ledger | COMPLETE | V008 hardening and live-DB integration test exists |
| Knowledge Graph API | COMPLETE | entity/edge/history/query/mutation routes |
| Governed enterprise search | COMPLETE | V010, cursor crypto, retention/work bounds and API tests |
| Studio BFF | COMPLETE | constrained BFF and delegated search/read proxy |
| Studio application | PARTIAL | buildable UI; three visible routes remain placeholders |
| Entity exploration | COMPLETE | search/entity workspaces and tests |
| Knowledge Graph Explorer | COMPLETE | native SVG/list progressive explorer and tests |
| Documentation generation | NOT REQUIRED FOR V1 | no accepted v1 runtime requirement |
| Decision/query capability | PARTIAL | KG query exists; Decision UI/domain service is absent |
| Operational health | COMPLETE | bounded `/healthz` and `/readyz` contracts |
| Migrations | COMPLETE | ordered/checksummed migrations and recovery guards |
| Startup validation | COMPLETE | production fail-fast configuration tests |
| Configuration governance | PARTIAL | validated settings; target production values absent by design |

## 5. Security release review

### Positive evidence

- Tokens are validated for signature, issuer, exact audience, expiry, and delegated credential
  constraints. Delegated KG operations do not fall back to a service-only principal.
- Studio session identifiers are opaque HttpOnly, Secure, SameSite cookies; PKCE/state/nonce,
  CSRF, logout invalidation, fixed redirects, and expiry behavior are tested.
- Tenant and clearance are server-derived. Policy and classification failures are fail-closed.
- Search is POST-only through the BFF, query-confidential, cursor-encrypted, rotation-safe,
  retention-bounded, work-bounded, and does not disclose denied/hidden totals.
- Audit records Human Principal and Acting Service; projector delivery is retryable and the
  authoritative ledger/custody chain has integration coverage.
- Production settings reject development secrets, insecure transports, unknown service-prefixed
  variables, and unsafe pool/session/search bounds.
- Production pods use non-root users, read-only roots, dropped capabilities, seccomp, resource
  bounds, no service-account token automount, and default-deny network policy.
- Python locks use hashes; npm audit reports zero vulnerabilities; CI runs pip-audit, gitleaks,
  SBOM generation, dependency governance, and container scanning.

### Findings

| ID | Severity | Release class | Finding |
| --- | --- | --- | --- |
| SEC-01 | HIGH | P0 | No deployable Studio frontend artifact means the intended browser trust boundary cannot be operated as a complete product. |
| SEC-02 | MEDIUM | P1 | Runtime Trivy gates only `CRITICAL`; HIGH image vulnerabilities are reported neither as a blocking gate nor an explicit accepted-risk artifact. |
| SEC-03 | MEDIUM | P1 | External egress destinations, TLS endpoints, SecretStore, and real tenant/client inventory are unresolved target-environment inputs; production trust cannot be evidenced until qualification. |
| SEC-04 | LOW | P2 | Default tests emit short-HMAC-key warnings in synthetic projector tests; fixtures should meet production-equivalent cryptographic minimums. |
| SEC-05 | INFORMATIONAL | P2 | Committed local-development credentials are clearly marked and rejected in production; continue secret scanning and do not treat them as deployable values. |

No committed production secret was identified by repository inspection. The connected CI gitleaks
run was not reproduced locally.

## 6. Data, database, and projection review

Migration discovery enforces ordering and checksums. Runtime and migrator roles are separated;
V005/V001 dirty-state recovery is narrowly guarded. Constraints, foreign keys, indexes, search
indexes, authoritative revisions, outbox, mutation ledger, evidence custody, and retained search
representations are repository-controlled.

A clean database has repository-controlled bootstrap and migration commands. Existing environments
have forward migration and bounded recovery paths. CI includes real PostgreSQL provisioning,
migration, mutation, search, evidence and backup/PITR tests, but the local default run skipped those
requiring external datastores.

PostgreSQL remains authoritative. Neo4j is a derived projection and is not consulted as an
authorization authority. Projection head/hash checks, stale detection, checkpointing, retry and
repair are implemented. Neo4j loss can degrade projection-dependent behavior, but does not make
Neo4j authoritative or permit unsafe results; authoritative reads/fallback stay PostgreSQL-backed.

## 7. End-to-end evidence

| Required chain | Evidence level | Assessment |
| --- | --- | --- |
| Browser → Studio → BFF → exchange → KG → PostgreSQL | NOT TESTED live | Component and mocked HTTP tests exist; no deployed browser chain and Studio is not deployable from the production bundle. |
| Governed search → PolicyEngine → Audit | INTEGRATION TESTED in parts | Real PostgreSQL search tests and mocked BFF/KG transport tests; no live full chain. |
| Mutation → PostgreSQL → outbox → Neo4j | INTEGRATION TESTED | CI real PostgreSQL/Neo4j persistence and mutation coverage; not a deployed environment test. |
| Delegated operation → Audit → Projector → ledger | INTEGRATION TESTED | Authoritative Audit E2E uses real PostgreSQL with in-process HTTP TestClient; not live network E2E. |
| Crash/restart → pending dispatch → replay | UNIT/INTEGRATION TESTED | worker/replay/idempotency tests; no production restart exercise. |

No Playwright/Cypress/Selenium suite or live multi-service environment qualification is present.
MockTransport and TestClient evidence is not called live E2E.

## 8. Deployment, CI/CD, and supply chain

The five governed EMG images are multi-stage, non-root, health-checked and dependency-controlled.
Tag releases build once, scan, publish to GHCR, capture immutable digests, sign with keyless Cosign,
verify identity, attest provenance, retain CycloneDX SBOMs, and create resolved/rollback bundles.

The production overlay deliberately contains invalid image fixtures and example endpoints. Only a
generated resolved bundle is deployable. Rollout sequencing is documented but not automated by
the repository. Promotion approval relies on an externally configured GitHub environment. No
deployment workflow applies the bundle to staging or production, performs smoke tests, or records
rollback rehearsal.

CI enforces Python lint, formatting, strict typing, tests, production rendering, provisioning,
dependency checks, pip audit, secret scan, SBOM, container build/critical scan, and real datastore
integration. It does **not** invoke Studio npm test/typecheck/lint/build/audit; those were run
locally for this review. Studio is also absent from container inventory and release finalization.

RC-1G is therefore only partially closed: registry, signing, provenance and immutable bundles now
exist in code, but complete runtime inventory, witnessed publication, promotion and rollback remain
unresolved.

## 9. Observability, resilience, and capacity

Services emit structured logs and correlation data. Health/readiness and several collector-ready
counter/gauge/histogram observations exist, including projector backlog, mutation dispatch, schema
operations, and search retained-representation cardinality/storage. The projector telemetry module
explicitly states that no metrics backend is provided.

No PrometheusRule, alert-manager rules, dashboards, or equivalent provisioned alerts were found for
service availability, Audit failure, projector/dispatch backlog, DB exhaustion, projection
divergence, search retention/storage, authentication failures, error rate, or latency. Documentation
that operators should alert is not an alert implementation.

Graceful shutdown, bounded pools/timeouts, retry, replay and idempotency are tested. PostgreSQL
backup/PITR scripts and a CI real recovery rehearsal exist; documented RPO is five minutes and RTO
four hours. Production scheduling, encryption/KMS custody, cross-region storage, Audit-specific
recovery exercise, secrets recovery, and a witnessed environment restore are not evidenced.

Resource requests/limits exist, but serving workloads are single replica. No approved platform SLO,
production load/stress test, query-plan regression gate, or capacity qualification was found.

## 10. Studio/product readiness

| Route | Classification |
| --- | --- |
| `/`, `/dashboard` | PRODUCTION CAPABILITY |
| `/search` | PRODUCTION CAPABILITY |
| `/entities`, `/entities/[entityId]` | PRODUCTION CAPABILITY |
| `/knowledge-graph`, `/knowledge-graph/[entityId]` | PRODUCTION CAPABILITY |
| `/evidence` | PLACEHOLDER |
| `/timeline` | PLACEHOLDER |
| `/decisions` | PLACEHOLDER |

Implemented workspaces have EN/AR, RTL/LTR, responsive styles, error/session states and component
accessibility tests. The graph has a first-class keyboard-operable list. There is no browser-level
accessibility audit or mobile/browser E2E. The largest issue remains absence of a production Studio
runtime and ingress model.

## 11. Documentation readiness

Architecture overview, ADR register, deployment, configuration, infrastructure, security,
engineering, API architecture, testing strategy, release/rollback strategy, and PostgreSQL
backup/recovery documentation exist. Documentation is fragmented and frequently architectural
rather than an executable operator/end-user guide.

Before GA, consolidate or create: installation/upgrade procedure, complete configuration reference,
secret/key rotation operations, database administration, full DR runbook, monitoring/alert response,
incident response, troubleshooting, Studio administrator guide, Studio end-user guide, production
API reference publication, release checklist, rollback rehearsal, known limitations, and named
support/escalation ownership. These are documentation gaps, not authorization to create them in
this audit.

## 12. Release gaps

### P0 — release blockers (5)

1. **RC-P0-A — Studio production runtime missing.** Add a governed production image, Kubernetes
   workload/service/ingress routing, supply-chain inclusion and production startup/security model
   for `apps/studio`.
2. **RC-P0-B — No qualified production promotion.** Resolve real endpoints/secrets/egress/TLS,
   automate or execute ordered provisioning, run the first signed immutable release, and retain
   staging/production approval and rollback evidence.
3. **RC-P0-C — Production alerting absent.** Provision collection plus actionable alert rules for
   all mandatory service, database, audit, dispatch, projection, auth and search conditions.
4. **RC-P0-D — Recovery not operationally proven.** Configure production backup scheduling,
   encryption/KMS, retention and remote storage; conduct and retain a witnessed restore/PITR
   rehearsal meeting the approved RPO/RTO.
5. **RC-P0-E — Required live E2E qualification absent.** Exercise chains A–E in a production-like
   environment, including browser identity/delegation/search, mutation/projection/audit, and crash
   replay. Preserve evidence and failure diagnostics.

### P1 — required before GA (8)

1. Add Studio npm test/typecheck/lint/build/audit and frontend artifact checks to CI.
2. Decide/remove or implement the visible Evidence, Timeline, and Decisions placeholders before GA.
3. Close single-replica/HA readiness, including the BFF process-local session limitation or record
   the accepted controlled-production constraint.
4. Approve SLOs and perform representative load/capacity/pool/timeout qualification.
5. Make HIGH container vulnerabilities block or require explicit, expiring risk acceptance.
6. Execute live Keycloak, database migration/upgrade, Neo4j loss/repair, and Audit outage scenarios.
7. Rehearse application rollback and forward-compatible migration recovery with a released bundle.
8. Complete the operator, administrator, end-user, incident, upgrade, troubleshooting, limitations,
   and support documentation set.

### P2 — post-GA hardening (7)

1. Add automated browser accessibility and responsive/device testing.
2. Export collector-ready observations through a standardized metrics endpoint/backend.
3. Add query-plan regression and longer soak/stress suites.
4. Replace synthetic short HMAC test keys to remove cryptographic warnings.
5. Add multi-region/zone HA and regular chaos exercises beyond the initial controlled topology.
6. Automate documentation link/freshness/status validation.
7. Add recurring secret-rotation and disaster-game-day automation.

### P3 — future capability (4)

1. AI orchestration proposed in ADR-019.
2. Full knowledge-ingestion runtime proposed in ADR-020.
3. Broader enterprise API program proposed in ADR-021.
4. Full Decision Intelligence, Evidence, and Timeline product work beyond the accepted v1 core.

## 13. Scorecard

| Domain | Score |
| --- | ---: |
| Architecture | 88 |
| Core platform | 86 |
| Security | 82 |
| Identity | 86 |
| Authorization | 91 |
| Audit | 84 |
| Persistence/data integrity | 89 |
| Search | 91 |
| Studio/BFF | 70 |
| Testing | 77 |
| CI/CD | 81 |
| Deployment | 45 |
| Supply chain | 78 |
| Observability | 36 |
| Resilience/DR | 49 |
| Performance/capacity | 42 |
| Documentation | 58 |
| Operations | 38 |

The weighted score is 69. Architecture, security, authorization, persistence, deployment,
resilience, and operations receive 65% combined weight because failure there can violate trust or
cause unrecoverable loss. Core/product/testing/search receive 25%; documentation and performance
receive 10%. A weighted score cannot override a P0.

## 14. Top ten risks

1. Product UI cannot be deployed from the production bundle.
2. A first real signed/promoted release may expose untested workflow or registry assumptions.
3. Mandatory failures may remain invisible without alerts.
4. Backup artifacts may fail operational recovery despite CI rehearsal.
5. Cross-service browser/delegation behavior is unproven live.
6. Manual provisioning ordering can be executed incorrectly.
7. Single replicas create avoidable availability and maintenance interruption.
8. Capacity, pool and timeout defaults lack production workload qualification.
9. HIGH container vulnerabilities can pass the current image gate.
10. Placeholder routes and fragmented operations documentation create support and expectation risk.

## 15. Shortest safe critical path

| Package | Objective and scope | Dependencies | Likely files | Required tests | Owner fit | Parallel | Effort |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RC-A | Package/deploy Studio; include image in release inventory and ingress | none | `apps/studio`, `docker/dependencies.yaml`, `infra/kubernetes`, release validator/workflow | image, manifest, CSP/runtime, smoke, supply-chain | Codex | yes | MEDIUM |
| RC-B | Add Studio CI gates and browser production-like E2E harness | RC-A for deploy smoke | `.github/workflows`, `tests/e2e` | npm gates, Playwright browser chains A/B | Codex | yes | LARGE |
| RC-C | Provision metrics collection, dashboards and mandatory alerts | stable metric names | `infra`, telemetry config, operations docs | render/rule/unit plus alert fire tests | Codex + SRE | yes | LARGE |
| RC-D | Instantiate staging prerequisites and automate ordered promotion | RC-A, environment authority | `infra/environments`, CD workflow/scripts | provisioning, secret absence, staged rollout | Codex | partly | LARGE |
| RC-E | Production backup scheduler/KMS/retention and witnessed recovery | environment/KMS authority | `infra/backup`, operations evidence | backup, restore, WAL/PITR, RPO/RTO | SRE + Codex | yes | LARGE |
| RC-F | Live security/resilience qualification and rollback | RC-B–E | test/evidence artifacts; minimal product code | chains A–E, Neo4j loss, Audit outage, restart, rollback | Claude review + Codex harness | no, final gate | LARGE |
| RC-G | GA documentation/product cleanup and capacity approval | results from RC-C–F | `docs`, placeholder routes | doc validation, load tests, route tests | Claude docs/review + Codex tests | yes | MEDIUM |

Merge order: RC-A before RC-B/D; RC-C and RC-E can proceed independently; RC-D consumes RC-A;
RC-F runs only after A–E merge and deploy to staging; RC-G consumes final operating parameters.

Recommended branch boundaries are `feature/rc-studio-runtime`, `ci/rc-studio-e2e`,
`ops/rc-observability-alerts`, `ops/rc-promotion`, `ops/rc-recovery-proof`, and
`docs/rc-ga-operations`. Do not edit shared Kustomize or workflow files concurrently; assign
ownership and rebase downstream branches after RC-A.

## 16. Recommended first closure sprint

Start RC-A, RC-C, and RC-E in parallel. RC-A removes the structural deployment blocker and enables
browser qualification. RC-C and RC-E close independent safety blockers. In parallel, Claude should
adversarially review the Studio runtime threat model, alert coverage matrix, and recovery evidence
criteria without editing implementation branches. Begin RC-D after RC-A's runtime contract is
stable, then make RC-F the non-negotiable final release gate.

## 17. Validation evidence from this review

- Refreshed `origin/develop`; HEAD and remote both
  `8556137fd42dc840bda1c85fa1045c2bbd88dd12`.
- `make lint`: passed; Ruff passed and Black would leave 552 files unchanged.
- `make typecheck`: passed for 23 Python packages under strict mypy.
- `make test`: 2,294 passed, 103 skipped, 5 warnings out of 2,397 collected.
- Studio tests: 39 passed.
- Studio TypeScript, ESLint, and production Next.js build: passed.
- `npm audit`: zero vulnerabilities.
- ADR-041 provisioning validator: passed.
- Dependency manifest, drift, implicit dependency checks: passed.
- Dependency-checker tests: 33 passed.

Not executed locally: live PostgreSQL/Neo4j integration suite, live Keycloak, real recovery/PITR
integration, Docker image builds/Trivy, gitleaks, GHCR publication, Cosign verification, provenance,
Kubernetes apply, real External Secrets/TLS/egress, production alert firing, browser E2E, load/stress,
failover, rollback, or disaster recovery. Some are CI-defined; none was falsely reported as live.

## 18. Audit document boundary

This review creates only `docs/release/EMG_V1_RELEASE_CANDIDATE_CLOSURE_REVIEW.md`. It contains no
implementation fix. Recommended commit message after approval:

`docs(release): add EMG v1 RC closure review`
