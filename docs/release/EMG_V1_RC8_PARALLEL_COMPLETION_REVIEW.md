# EMG v1.0 RC.8 parallel completion review

**Review date:** 2026-08-13
**Release:** `v1.0.0-rc.8`
**Source commit:** `b3e6cc76f0df10d9f7566ea97575dadf4d7cebb1`
**Review branch:** `closure/v1-parallel-completion`
**Scope:** repository-only closure; no staging or production mutation
**Overall status:** **REPOSITORY READY; OPERATIONAL ACTIVATION PENDING**

This record supersedes no historical release evidence and makes no claim about live staging.
The RC-F evidence remains the latest integrated local qualification record. Live staging
activation, smoke/E2E evidence, recovery witness, rollback witness, and promotion approval must
be attached as separate environment evidence.

## 1. Executive closure verdict

The release candidate has no newly discovered repository implementation P0. RC-A through RC-F
closed the previously identified Studio-runtime, alert-definition, recovery-tooling,
promotion-tooling, and integrated-local-qualification gaps. The Cloud SQL role-convergence fix in
RC.8 preserves the ADR-034/ADR-041 least-privilege result while accommodating managed PostgreSQL.

Four operational P0s remain open: qualified staging promotion, alert delivery activation,
target-environment restore/PITR witness, and authenticated live E2E qualification. They cannot be
closed from this repository-only track.

Estimated v1 completion is **92%**: repository implementation and local qualification are
complete, while target configuration and witnessed operational evidence remain incomplete.

## 2. Repository audit findings

| Finding | Classification | Disposition |
| --- | --- | --- |
| Integration tests skipped without PostgreSQL, Neo4j, or Keycloak environment variables | EXPECTED_ENVIRONMENT_PLACEHOLDER | Run only against isolated test infrastructure or qualified staging; never silently count as live evidence |
| `registry.invalid` images and `*.example.invalid` endpoints in base/overlay templates | EXPECTED_ENVIRONMENT_PLACEHOLDER | Required non-deployable fixtures; release finalization rejects them from resolved bundles |
| Local Keycloak passwords and CI datastore passwords | TEST_ONLY | Clearly local/CI scoped; production validators reject unsafe configuration |
| `NotImplementedError` in test doubles | TEST_ONLY | Deliberate protocol stubs used to prove failure behavior |
| Historical ADR-027 plan references to xfail | FALSE_POSITIVE | Planning history; no active xfail was collected in the default suite |
| Empty `emg-entity-resolution` package | CAN_DEFER_POST_V1 | Governed by open D-A-002 and excluded from editable installation; no v1 dependency |
| AI orchestration, ingestion, broad enterprise API, and full Decision Intelligence | CAN_DEFER_POST_V1 | Proposed/future scope; no v1 release dependency |
| Visible `/decisions`, `/evidence`, and `/timeline` placeholder routes | DOCUMENTATION_ONLY | Known limitation; remove from navigation or implement only under separately approved post-v1 scope |
| Historical architecture register said ADR-042 was not started | DOCUMENTATION_ONLY | Corrected in this track to current implemented status |
| Default suite emits four short synthetic HMAC-key warnings | CAN_DEFER_POST_V1 | Test-fixture hygiene; production minimum-key validation is unchanged |
| `run-integration-tests.sh` still describes a Sprint 1 skeleton | CAN_DEFER_POST_V1 | Stale convenience wrapper; canonical CI and explicit integration suites are authoritative |
| Rollback gate checked distinct release and identical migration set but did not prove semantic version ordering | MUST_FIX_BEFORE_V1 | Corrected in this track with fail-closed governed-version parsing, chronology comparison, and regression tests |

No active source TODO, FIXME, XXX, debug bypass, production secret, disabled security gate, or
active xfail was found. Historical documents containing those words are not executable findings.

## 3. ADR compliance matrix

| ADR | Implementation | Validation/security evidence | Operational prerequisite | Status |
| --- | --- | --- | --- | --- |
| ADR-028 Audit Reconciliation | Audit Projector, bounded retry/replay, authoritative delivery | Worker, delivery, audit service, and PostgreSQL integration suites | Projector identities and live backlog observation | PASS / PENDING_LIVE |
| ADR-034 Security State and Service Trust | Durable refresh state, tenant-confined Audit, split DB roles, service token contract | Authorization, tenant, startup, provisioning, and role-escalation tests | Managed PostgreSQL credentials and live token issuers | PASS / PENDING_LIVE |
| ADR-035 Human Authentication | BFF Authorization Code + PKCE, opaque secure sessions | OIDC, cookie, CSRF, logout, and claim tests | Production Keycloak client, TLS, redirect URI | PASS / PENDING_LIVE |
| ADR-036 BFF Boundary | Same-origin browser boundary and constrained service proxy | Dependency-boundary and browser-security tests | Live ingress and network policy observation | PASS / PENDING_LIVE |
| ADR-037 Decision Domain Model | Accepted domain remains outside the controlled v1 runtime | No runtime claims made | Separate approved implementation if promoted into product scope | BLOCKED FOR FEATURE / POST_V1 |
| ADR-038 Human Delegation | RFC 8693 exchange and downstream human/acting-service attribution | 25-case real local Keycloak suite recorded by RC-F plus negative unit coverage | Live realm and authenticated chain | PASS / PENDING_LIVE |
| ADR-039 Backup/PITR | Physical backup, WAL, retention, manifests, recovery validation | Unit and real local PostgreSQL recovery rehearsal recorded by RC-F | Remote administrative separation, key custody, scheduled execution, witness | PASS / PENDING_LIVE |
| ADR-040 Runtime Supply Chain | Eight-image build/scan/SBOM/sign/provenance/resolved bundle workflow | Supply-chain, dependency, container-coverage, and manifest tests | Protected GitHub release run and retained live attestations | PASS / PENDING_LIVE |
| ADR-041 Production Provisioning | Governed roles, migrations, projector inventory, staged validation | Production validator and provisioning/infrastructure suites | Ordered target execution and environment inventory | PASS / PENDING_LIVE |
| ADR-042 Governed Search | V010, bounded PostgreSQL search, encrypted cursors, BFF and Studio | Search persistence/API/config/cursor/BFF/Studio tests | Live authorization, Audit, storage, and retention observation | PASS / PENDING_LIVE |

ADR-032 and ADR-033 remain partial by their own recorded phase boundaries; their unimplemented
read-path/normalizer extensions are not prerequisites for the frozen v1 capability set. ADR-019,
ADR-020, and ADR-021 remain proposed and do not authorize release scope.

## 4. Production readiness checklist

| Area | Status | Repository evidence / closure condition |
| --- | --- | --- |
| Immutable image digests and complete image inventory | PASS | Eight governed runtime/deployment-tool images; finalized bundles reject fixtures and mutable references |
| ConfigMaps and startup validation | PASS | Environment settings are explicit and fail closed |
| Secret and ExternalSecret references | PASS | No literal production Secret; target SecretStore and values remain environment-owned |
| Service accounts / Workload Identity | PENDING_LIVE | Least-privilege manifests exist; cloud bindings must be witnessed externally |
| TLS, DNS, ingress, and egress | PENDING_LIVE | Placeholder-free qualified environment required |
| Network policies and pod hardening | PASS | Default deny, scoped flows, non-root/read-only/drop-capability/seccomp contracts tested |
| Requests, limits, probes, and graceful shutdown | PASS | Manifest and service tests cover bounded lifecycle behavior |
| Disruption handling / HA | BLOCKED | Controlled v1 topology must be explicitly accepted; BFF process-local sessions constrain replica model |
| PostgreSQL migrations and role ordering | PASS | ADR-041 validator and Cloud-SQL-compatible fail-closed convergence |
| Neo4j projection and rebuild | PASS | PostgreSQL authority, checkpoints, repair, and replay tests; live rehearsal pending |
| Backup, WAL, retention, restore, and PITR | PENDING_LIVE | Local real rehearsal passes; remote custody and witnessed target restore remain open |
| Metrics, rules, dashboards, and runbook | PASS | RC-C artifacts and infrastructure tests |
| Alert evaluator, receiver, and delivery | PENDING_LIVE | Backend/provider selection and witnessed alert delivery are environment-owned |
| Logging and audit evidence | PASS | Structured logging, Audit service/projector, custody/evidence verification |
| Credential/certificate rotation | PENDING_LIVE | Contracts documented; target-provider procedures and witness required |
| Failure behavior | PASS | Authentication, authorization, audit, search, projection, and recovery paths fail closed |
| Capacity/SLO qualification | BLOCKED | Approved SLOs and representative target load evidence are absent |

## 5. Release tooling review

The governed path binds source commit to a complete image set, scan/SBOM checksums, immutable OCI
digests, signatures/provenance, source and resolved bundle hashes, environment namespace, and a
staged provisioning contract. Promotion rejects evidence for another manifest, unwitnessed staging,
failed checks, missing protected-environment identity, missing smoke evidence, or missing rollback
rehearsal. The templates deliberately retain environment placeholders while finalization rejects
them from deployable evidence.

One narrow hardening defect was corrected: `rollback_gate()` previously proved a candidate was
distinct and had an identical migration-set hash, but did not prove the candidate version predated
the current version. It now accepts only the governed `vMAJOR.MINOR.PATCH[-rc.N]` form and rejects
equal, newer, or unparseable candidates. RC ordering and RC-to-GA ordering have explicit tests.
This does not mutate or reinterpret any live RC.8 evidence; it changes future release-gate behavior
only after this branch is reviewed and merged.

Environment-owned resources are not release-created merely because their references appear in a
bundle. SecretStore, cloud IAM/Workload Identity, DNS/TLS, managed datastores, Keycloak topology,
remote backup custody, and monitoring delivery remain operational inputs. Their existence must be
verified during qualification rather than inferred from render success.

## 6. Documentation package index

The following index is the final package structure. Existing authoritative documents are reused;
`PENDING` means the topic needs a consolidated audience-specific guide or live evidence before GA.

### Executive

| Deliverable | Source | Status |
| --- | --- | --- |
| Executive Overview / Product Scope | `docs/executive/EXECUTIVE_SUMMARY.md`, `docs/product/EMG_PD-001_MVP_FREEZE_CONTROL_RECORD.md` | COMPLETE |
| Architecture / Security / Governance Summary | `docs/architecture/EMG_Architecture_Baseline_v1.0_Final.md`, `docs/security/SECURITY_ARCHITECTURE_OVERVIEW.md`, `docs/governance/GR-001_EMG_DOCUMENTATION_GOVERNANCE_FRAMEWORK.md` | COMPLETE |
| Release & Support Model | release/operating documents and `docs/v1/SUPPORT_AND_ESCALATION.md` | COMPLETE; live assignees PENDING_LIVE |

### User

| Deliverable | Source | Status |
| --- | --- | --- |
| End User / Studio Guide | `docs/v1/USER_GUIDE.md` | COMPLETE |
| Authentication/Login Guide | V1 user guide and frontend authentication flow | COMPLETE |
| Search/Decision Workspace Guide | V1 user guide and ADR-042 | COMPLETE; Decision workspace explicitly POST_V1 |
| User troubleshooting | V1 user and troubleshooting guides | COMPLETE |

### Operations

| Deliverable | Source | Status |
| --- | --- | --- |
| Administrator / Deployment / Environment Configuration | V1 administrator, deployment and overlay documents | COMPLETE; target values PENDING_LIVE |
| Secret Management / Keycloak | `docs/infrastructure/SECRETS_MANAGEMENT.md`, ADR-035/038/041, Identity README | PENDING provider-specific witnessed procedure |
| PostgreSQL / Neo4j Operations | `docs/engineering/persistence-operations.md`, infrastructure operations and projection docs | COMPLETE; target rehearsal pending |
| Backup / Restore / DR | `docs/operations/postgresql-backup-recovery.md` | COMPLETE; live evidence pending |
| Rollback / Upgrade | release-promotion and rollback documents | COMPLETE; live rehearsal PENDING_LIVE |
| Incident Response / Monitoring / Alerting | V1 security/support guides and alert runbook | COMPLETE; live assignments/routing PENDING_LIVE |
| Troubleshooting / Failure Modes / Maintenance | V1 troubleshooting and administrator guides | COMPLETE |

### Engineering

| Deliverable | Source | Status |
| --- | --- | --- |
| Developer / Repository / Local Development / Contribution | V1 engineering handbook, root README and contribution documents | COMPLETE |
| Architecture Handbook / ADR Index | architecture README/baseline/status and ADR register | COMPLETE |
| Persistence / Authorization / Identity / Audit / Projector / Studio-BFF | engineering, security, backend, service and app documents | COMPLETE |
| API Guide and examples | `docs/v1/API_COOKBOOK.md`, backend architecture, generated OpenAPI | COMPLETE |
| Testing / CI-CD / Release / Dependencies / Security Engineering | engineering testing strategy and devops/security documents | COMPLETE |
| Coding Standards / Contribution | engineering coding standards and `CONTRIBUTING.md` | COMPLETE |

### Security and governance

| Deliverable | Source | Status |
| --- | --- | --- |
| Threat Model / Trust Boundaries / Least Privilege / Tenant Isolation | security suite plus ADR-025/026/034/036/038/041 | COMPLETE |
| Credential Lifecycle / Access Control Matrix | V1 security operations guide and IAM/security documents | COMPLETE; live custodians/schedules PENDING_LIVE |
| Audit Evidence / Data Protection | Audit/logging and data-protection documents plus ADR-028/039 | COMPLETE |
| Supply Chain / Vulnerability / SBOM / Signing / Provenance | ADR-040 and devops dependency/artifact documents | COMPLETE |
| Operational Security Checklist | `docs/v1/SECURITY_OPERATIONS_GUIDE.md` | COMPLETE; sign-off PENDING_LIVE |

### Release

| Deliverable | Source | Status |
| --- | --- | --- |
| v1.0 Release Notes | `CHANGELOG.md` plus final tag evidence | PENDING final GA version/date |
| Known Limitations / Deployment Preconditions | this review, RC closure review, activation plan | COMPLETE for RC; refresh for GA |
| Staging Qualification Record | RC-D generated evidence contract and RC-F example | TEMPLATE COMPLETE / LIVE PENDING |
| Production Promotion Record | promotion gate plus protected-environment approval evidence | TEMPLATE COMPLETE / LIVE PENDING |
| Rollback Evidence | generated rollback bundle and operations runbook | TEMPLATE COMPLETE / LIVE PENDING |
| Recovery Evidence | recovery manifest/verification and operations runbook | TEMPLATE COMPLETE / LIVE PENDING |
| Operational Acceptance Checklist | this checklist and activation plan | COMPLETE / SIGN-OFF PENDING |

Documentation content that depends on a selected monitoring backend, KMS, backup provider, staging
platform, target DNS/TLS, or live witness remains intentionally provider-neutral. No unapproved
provider has been selected.

## 7. Scope freeze and deferred work

The following are **POST_V1** unless a separate authority changes scope: AI orchestration,
knowledge-ingestion runtime, broad enterprise API program, full Decision Intelligence UI/service,
entity-resolution ownership resolution, automated browser accessibility/device matrix, multi-region
HA, chaos/soak suites, query-plan regression automation, and documentation-site automation.

No product feature is required from this parallel track. Repository changes are limited to status
reconciliation and closure documentation.

## 8. Remaining blockers and ownership

| Blocker | Exact closure evidence | Owner/dependency |
| --- | --- | --- |
| Qualified staging promotion | Exact RC.8 digest set, protected approval, resolved config, ordered provisioning, smoke, distinct rollback witness | Live staging activation track |
| Production alerting activation | Approved evaluator/receiver, scrape/rule health, safe fired/resolved test notification, operator acknowledgement | Operational decision and target access |
| Recovery/PITR witness | Remote administratively separate backup/WAL, key custody/escrow, isolated target restore, measured RPO/RTO, ledger/search/projector checks | Recovery operator, security custodian, witness |
| Authenticated live E2E | Browser OIDC/PKCE/session/delegation/search/explorer plus mutation/projection/audit/replay evidence | Live staging identity and service environment |

## 9. RC.8 impact and merge sequencing

The documentation corrections do not change RC.8 artifacts, runtime behavior, staging activation,
or architecture. The rollback chronology correction changes release-gate behavior. If this branch
is merged, **RC.9 is required** so the governed release evidence is generated from the corrected
tooling rather than treating RC.8 as though it contained that validation.

Recommended sequence:

1. Complete live staging activation without rebasing onto this parallel branch.
2. Preserve live evidence and any environment-owned decisions in a dedicated activation change.
3. Review and merge this parallel closure change after resolving any factual differences against
   the live evidence.
4. Cut RC.9 from the merged source because release-gate behavior changed.
5. Run final staging, rollback, recovery, alert, and E2E qualification against RC.9.
6. Convene production promotion approval only after all four operational P0s are closed.

## 10. Claude handoff requirements

`CLAUDE_HANDOFF_REQUIREMENTS`

- Exact staging cluster/environment identifier and qualified RC.8 image manifest checksum.
- Placeholder-free endpoint, ingress, egress, TLS, and ExternalSecret validation result.
- ADR-041 stage-by-stage completion evidence, including Cloud SQL role verification.
- Keycloak realm/client/claim/token-exchange qualification without secret or token disclosure.
- Studio/BFF authenticated browser smoke and downstream Knowledge Graph/Audit evidence.
- Monitoring evaluator/receiver decision, rule-load result, and witnessed alert delivery.
- Remote backup/WAL custody and encryption/escrow decision plus witnessed restore/PITR evidence.
- Distinct rollback target identity, proof that it predates RC.8, compatibility result, and witness.
- Final status for each P0 using only `PASS`, `PENDING_LIVE`, or `BLOCKED`, with named witness role.
- Any divergence from repository assumptions, reported as evidence rather than silently normalized.

## 11. Final adversarial audit classification

| Class | Findings |
| --- | --- |
| P0 | None in repository scope |
| P1 | None remaining after rollback chronology correction and documentation consolidation |
| P2 | Synthetic short-HMAC test warnings; stale Sprint-1 integration convenience script; consolidate generated API publication when a public distribution channel is approved |
| POST_V1 | ADR-037 implementation, AI/ingestion/API expansion, entity-resolution ownership, advanced HA/chaos/load/accessibility/documentation automation |
| FALSE_POSITIVE | `registry.invalid`/`example.invalid` source fixtures rejected during finalization; localhost/dev passwords confined to local/test defaults and rejected by production validation; pinned CI service images; localhost container health checks; TODO/xfail words inside historical documents; historical RC review status explicitly marked historical |

No unpinned production runtime image, mutable resolved reference, committed production secret,
active debug bypass, active xfail, unsafe production default, migration inconsistency, or stale
current ADR implementation status was found. Provider values, live identities, support assignees,
SLO/HA acceptance, and operational witnesses remain `PENDING_LIVE` or require human approval.
