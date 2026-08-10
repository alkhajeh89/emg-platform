# RC-F integrated live qualification evidence

**Qualification date:** 2026-08-11
**Source commit:** `f78d4e187d363d564737722e46a536c5dbb1e1bd`
**Branch:** `release/rc-f-integrated-live-qualification`
**Environment:** developer workstation, Docker Desktop, local PostgreSQL, and
isolated test containers
**Overall result:** **NO-GO**

This package records the strongest repository-controlled and environment-available
qualification performed for RC-F. It is not staging or production evidence. No
production credentials, tenant data, raw search queries, tokens, private keys, or
reusable secrets are included.

## Capability matrix

| Capability | Classification | Evidence |
| --- | --- | --- |
| Docker engine and Compose | AVAILABLE NOW | Docker client/server 29.7.2; Compose 5.3.1 |
| Kubernetes client and local cluster | AVAILABLE WITH LOCAL TEST INFRA | kubectl 1.36.1; single Docker Desktop control-plane context |
| PostgreSQL | AVAILABLE NOW | local PostgreSQL 16.14 plus isolated test instances |
| Neo4j | AVAILABLE WITH LOCAL TEST INFRA | pinned Neo4j 5 Community container used for integration tests |
| Keycloak | AVAILABLE WITH LOCAL TEST INFRA | isolated pinned Keycloak 25 ADR-038 verification environment |
| Browser build/test tooling | AVAILABLE NOW | Studio Vitest, ESLint, TypeScript, and Next.js build |
| Real browser identity E2E | NOT AVAILABLE | browser control exists, but no running authenticated same-origin Studio/BFF product environment |
| GitHub repository/workflows | AVAILABLE NOW | authenticated GitHub context and workflow metadata read access |
| GHCR package inspection | NOT AVAILABLE | current credential lacks `read:packages` |
| Cosign executable | AVAILABLE NOW | local executable present; no exact RC-F published digest set exists |
| GitHub OIDC signing/provenance | REQUIRES GITHUB/OIDC | only protected tag workflow can issue governed evidence |
| Staging cluster/context | REQUIRES STAGING ENVIRONMENT | sole context is `docker-desktop`; no staging context or credentials |
| Production cluster/context | REQUIRES PRODUCTION ENVIRONMENT | no production context or credentials |
| Monitoring evaluator/delivery | NOT AVAILABLE | no Prometheus-compatible evaluator, Alertmanager, or receiver is running |
| External Secrets | REQUIRES STAGING ENVIRONMENT | operator/CRDs and target SecretStore are absent locally |
| Remote backup/custody and escrow | REQUIRES PRODUCTION ENVIRONMENT | no remote repository, KMS wrapper, or escrowed key context available |

## Machine-generated execution evidence

| Qualification | Classification | Result |
| --- | --- | --- |
| ADR-038 RFC 8693/Keycloak verification | REAL LOCAL INTEGRATION | 25 passed; positive/negative exchange, expiry, audience, attribution |
| PostgreSQL + Neo4j persistence/mutation/audit suites | REAL LOCAL INTEGRATION | 85 passed |
| Full backup and PITR rehearsal | REAL LOCAL INTEGRATION | 1 passed; WAL replay, recovery-point assertion, ledger verification, truncation rejection |
| Complete Python test suite | MIXED: STATIC, MOCKED, AND LOCAL TEST INTEGRATION | 2501 passed, 103 skipped, 5 warnings |
| Studio tests | MOCKED INTEGRATION | 39 passed |
| Studio lint/typecheck/build | STATIC VALIDATION | passed; ten routes generated |
| Eight governed runtime image builds and Trivy scans | REAL LOCAL INTEGRATION | all built; zero CRITICAL findings under the repository blocking policy |
| Browser Studio startup/failure boundary | REAL LOCAL INTEGRATION | Studio loaded at `/dashboard`; absent BFF produced the governed fail-closed unavailable screen |
| Kubernetes production/staging rendering | STATIC VALIDATION | both rendered successfully; ADR-041 provisioning validator passed |
| Dependency/type/format/pre-commit gates | STATIC VALIDATION | dependency manifest/drift/imports, mypy, Ruff, Black, npm audit, and pre-commit passed |

The real-datastore suite covered authoritative PostgreSQL state, Neo4j projection,
atomic mutation, dispatch, and authoritative Audit delivery. The recovery rehearsal
used real PostgreSQL processes but synthetic local copy wrappers in place of remote
encryption, signature custody, and escrow. The Keycloak suite used genuine token
exchange but did not use the browser Authorization Code flow or the deployed Studio
BFF.

## Qualification targets

| Chain | Classification | Result |
| --- | --- | --- |
| Browser trust chain | REAL LOCAL INTEGRATION (partial) | Studio startup and absent-BFF fail-closed behavior witnessed; authentication and downstream chain not executed |
| Governed search browser-to-audit | MOCKED INTEGRATION | component/API tests pass; no browser/network chain |
| Knowledge Graph Explorer | MOCKED INTEGRATION | Studio component tests pass; no authenticated browser expansion |
| Mutation path | REAL LOCAL INTEGRATION | PostgreSQL mutation, outbox/dispatch, projection, and Audit suites pass |
| Audit path | REAL LOCAL INTEGRATION | delegated attribution and authoritative ledger suites pass |
| Recovery | REAL LOCAL INTEGRATION | isolated full backup/PITR passes; target-environment custody/rebuild unwitnessed |
| Observability | STATIC VALIDATION | metric/rule/dashboard tests only; no evaluator or alert delivery |
| Release/promotion | STATIC VALIDATION | repository gates exist; exact RC-F publication/staging/rollback not executed |

## Security and failure evidence

Repository tests and the real-local suites exercised fail-closed invalid/expired
delegation, unauthorized exchange, audience/tenant mismatch, audit outage/retry,
cursor tampering, bounded search requests, backup authorization, missing key/config,
corrupted/truncated recovery evidence, missing release evidence, bundle drift, and
promotion/rollback gate rejection. These are mixed static, mocked, and real-local
tests; none is represented as a production failure injection.

No production outage or destructive environment test was induced.

## Release-set, signing, provenance, staging, and rollback

No immutable release manifest exists for source commit `f78d4e1`. GitHub reports no
workflow run for that exact commit. Earlier tagged runtime-image workflows through
`v1.0.0-rc.5` succeeded, but those tags identify older commits and do not qualify
this source. Therefore RC-F has no claim of current image digests, retained SBOMs,
current Cosign signatures, current GitHub provenance, staging deployment, smoke
qualification, or rollback qualification.

The protected `production-release` GitHub environment exists with a required
reviewer, but its existence is not approval evidence and no promotion was attempted.

## Recovery and alerting status

The local recovery rehearsal proves executable backup/PITR mechanics and integrity
checks. It does not prove remote administrative separation, production scheduling,
key custody/escrow, target configuration, measured production RPO/RTO, Neo4j rebuild,
or a witnessed target-environment restore.

Metrics, portable alert rules, dashboards, and their repository tests exist. No
monitoring backend, rule evaluator, receiver, or delivery route was available, so no
alert was fired or delivered and Alerting P0 remains open.

## P0 status and recommendation

| P0 | Status | Closure requirement |
| --- | --- | --- |
| Promotion | OPEN | publish/sign/attest this exact source, deploy exact set to staging, smoke and roll back a distinct qualified set |
| Alerting | OPEN | activate scraper/evaluator and witness routed alert delivery |
| Recovery | OPEN | configure remote custody and keys; witness target-environment restore/PITR and reconciliation within approved RPO/RTO |
| Live E2E | OPEN | execute authenticated browser and service chains A-E in a production-like environment |

**Remaining P0 count: 4.**

The provisional evidence-informed readiness score is **82/100**. Repository
implementation and real-local integration are materially stronger than the original
69/100 review, but the score cannot override the four open P0s.

**Recommendation: NO-GO.** Final Readiness Review must not begin as a release-approval
review. An operational activation review may begin to assign environments, owners,
credentials, and witnessed execution dates for the four closure requirements.

## Activation checklist

1. Create a protected release tag from the approved source and retain the exact
   manifest, digest-bound Trivy reports, SBOMs, Cosign verification, and provenance.
2. Configure staging External Secrets, endpoints, TLS, egress, datastores, Keycloak,
   recovery storage, and telemetry without reusing production credentials.
3. Apply ADR-041 stages, deploy the exact resolved set, and capture readiness and
   browser/service smoke evidence without sensitive request content.
4. Qualify rollback to a distinct, complete, migration-compatible prior release.
5. Activate the selected monitoring evaluator and routing system; safely trigger and
   witness at least one alert end to end.
6. Configure remote backup/WAL custody and escrow; perform the witnessed isolated
   target restore, Neo4j rebuild, dispatch/search verification, and RPO/RTO review.
7. Run the browser trust, search, Explorer, mutation, Audit, and crash/replay chains
   in the production-like staging environment and retain machine and human witness
   records separately.

## Manual witness evidence

None. No staging operator, production operator, security custodian, alert recipient,
or restore reviewer witnessed an environment execution during RC-F.
