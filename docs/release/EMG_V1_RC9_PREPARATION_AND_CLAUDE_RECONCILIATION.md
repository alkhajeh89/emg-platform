# EMG v1 RC.9 preparation and Claude reconciliation

**Prepared:** 2026-08-13
**RC.8:** `v1.0.0-rc.8` at `b3e6cc76f0df10d9f7566ea97575dadf4d7cebb1`
**Committed source reconciliation:** ADR-043 Identity durable refresh-state and recovery-governance
implementation at `464496238103978ec422c5d833be2f1800747777`; RC.9 rollback-version-chronology
release tooling at `76a30803ea930c6f5778ab10472ace812e63b5ac`. Both are independently reviewed and
committed on this branch. The final documentation/source-reconciliation commit remains
`PENDING_REVIEW`.
**RC.9 status:** NOT CREATED
**Live state:** OWNED BY CLAUDE; NOT MODIFIED BY THIS TRACK

## Classification vocabulary

- `REPOSITORY_FACT`: proven by source/tests at the candidate commit.
- `LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED`: target execution and witness are absent here.
- `RC8_EVIDENCE`: retain unchanged and associate only with RC.8.
- `RC9_REQUALIFICATION_REQUIRED`: must be rerun against the eventual RC.9 commit/artifacts.
- `POST_V1`: outside frozen v1 scope.

## Changes that must enter RC.9

| Change | Classification | Migration/runtime impact |
| --- | --- | --- |
| Rollback candidate governed-version chronology validation | REPOSITORY_FACT — committed `76a30803ea930c6f5778ab10472ace812e63b5ac` | Release tooling only; no database migration or application behavior |
| Regression tests for equal/newer/malformed and RC/GA ordering | REPOSITORY_FACT — committed `76a30803ea930c6f5778ab10472ace812e63b5ac` | Test only |
| ADR-042 register reconciliation | REPOSITORY_FACT | Documentation only |
| Accepted ADR-043 Identity durable refresh-state implementation | REPOSITORY_FACT — committed `464496238103978ec422c5d833be2f1800747777` | Isolated Identity migration/history, governed roles/adoption/grants, Stage-50 validation, schema-qualified runtime SQL, secret references, and recovery invalidation; migration set changes and requires full RC.9 qualification |
| Accepted ADR-043 Amendment 1 recovery-freshness decision (revised 2026-08-14, narrowly remediated 2026-08-14, further remediated 2026-08-14, authority-linearization remediated 2026-08-14, accepted 2026-08-14 after fifth independent review) | ACCEPTED_PENDING_IMPLEMENTATION_REVIEW | Requires an Approved Recovery Authority with platform-guaranteed monotonic non-reused version history and a serialized-rotation guarantee decided at a single authority-side linearization point (native CAS, or another genuine provider-native serialization primitive distinct from version creation itself — not a bare mutable UUID and not a read-verify-after-write detection procedure), gated by an explicit eight-property authority qualification gate, carries that authority revision alongside the generation through materialization/PostgreSQL/readiness comparisons, and adds a four-part recovery fencing protocol (named fence owner; workload, database-session, and a two-phase network fence — reconciliation-fence phase restricted to `emg_identity_migrator`, readiness-qualification-fence phase admitting only the freshly started `emg_identity_app` workload identity; mandatory positive evidence per fence and per phase transition). Fence release is an explicit nine-step ordered gate — the network-fence phase transition is its own evidenced step — requiring fresh-workload startup and independently-proven readiness before any traffic/database-access restoration; the network fence has explicit fail-closed failure semantics and adversarial test coverage for both phases, matching the other two fences, now extended with authority-rotation-layer adversarial tests and explicit per-stage rotation crash semantics. Revised in response to the first independent review's two P0 findings (P0-A external-authority rollback protection, P0-B enforceable recovery fencing); narrowly remediated in response to the second independent review's two remaining explicitness findings (A9.6 fence-release ordering, A9.7/A12 network-fence enumeration); further remediated in response to a third independent review's FAIL verdict, which found a contradiction between the network fence's migrator-only scope and the fresh workload's need for database access, and an unverified provider-capability claim (AWS Secrets Manager removed as a qualifying example; GCP Secret Manager's qualification restated via a documented detection procedure rather than a false native-CAS claim); authority-linearization remediated in response to a fourth independent review's FAIL verdict, which found that read-verify-after-write detection is not a linearizable serialization primitive and that GCP Secret Manager's documented consistency guarantees do not cover the version-history read that detection procedure depended on — GCP Secret Manager alone no longer qualifies as an Approved Recovery Authority for concurrent generation rotation under this amendment. A fifth independent review found no remaining material architecture, concurrency, replay, fencing, recovery, or privilege gap and accepted the amendment. No new architecture component was required at any stage. Acceptance authorizes a separate, subsequent implementation review of the two P0 remediations; it does not itself authorize target execution, staging, or RC.9 build |
| V1 documentation and closure/reconciliation package | REPOSITORY_FACT | Documentation only |

The ADR-043 implementation and rollback-chronology release-tooling changes above are each committed
to this branch (`464496238103978ec422c5d833be2f1800747777` and
`76a30803ea930c6f5778ab10472ace812e63b5ac` respectively, each independently reviewed before
commit). The ADR-042 register reconciliation and V1 documentation/closure package remain
uncommitted pending this documentation reconciliation; their commit ID is `PENDING_REVIEW` until
that commit is created and independently reviewed.

## Evidence regeneration

ADR-043 was accepted on 2026-08-14 and its repository implementation introduces an isolated
Identity migration stream. The resulting migration-set change must be included in the eventual
RC.9 migration-set assessment and recovery/rollback qualification.

Independent implementation review identified two unresolved P0 findings: exact legacy-adoption
security-state validation and replay-resistant post-restore freshness. ADR-043 Amendment 1 is
Proposed to decide the latter and clarify that the former is already required by D-6. A first
independent architecture/security review of that proposal did not accept it, finding the
external authority's non-reuse requirement unenforced (P0-A) and the recovery fencing discussion
insufficiently normative (P0-B). Amendment 1 was revised the same day to require a
capability-qualified Approved Recovery Authority with monotonic non-reused version history and a
serialized-rotation guarantee, an authority-revision value carried alongside the generation
throughout, and a named-owner recovery fencing protocol with mandatory positive evidence per
fence. A second independent review found two remaining explicitness gaps in the fence-release
ordering and network-fence failure/test coverage, remediated the same day. A third independent
review FAILED the amendment, finding a contradiction between the network fence's migrator-only
scope and the fresh workload's need for database access to prove readiness, and an unverified
claim that three named secret-management providers all natively satisfy the required authority
capabilities. This was remediated the same day by splitting the network fence into two explicit,
separately evidenced phases and by restating the capability contract as a security property
satisfiable by either native provider CAS or a documented detection procedure, without introducing
any new architecture component. A fourth independent review FAILED the amendment again, finding
that the documented detection procedure ("mechanism 3b": an unconditional write followed by a
re-read of the authority's version history to verify a predecessor) is not a linearizable
serialization primitive — authoritative GCP Secret Manager documentation confirms strong
consistency only for directly accessing an already-known version number, not for listing or
ordering the version history the predecessor check depended on, so two coordinators could each
observe a stale ordering and each independently conclude their own rotation succeeded. This was
remediated the same day by redefining capability 3 as a strict single-linearization-point
requirement; restricting mechanism 3a to genuine native atomic conditional writes; restricting
mechanism 3b to a genuine alternative provider-native serialization primitive distinct from version
creation itself (an atomic lease, exclusive lock, or conditional metadata compare-and-set), with a
read-verify-after-write procedure no longer qualifying under any circumstance; removing the claim
that GCP Secret Manager alone qualifies as an Approved Recovery Authority for concurrent generation
rotation; adding an explicit eight-property authority qualification gate; rewriting the rotation
algorithm around one authority-side atomic accept/reject step with explicit crash semantics for
every stage of rotation; and extending the adversarial test contract with authority-rotation-layer
tests — again without introducing any new architecture component, without making PostgreSQL a
freshness or lock authority, and without inventing a distributed lock service. A fifth independent
review adversarially re-verified the redefined capability 3, mechanisms 3a/3b, the qualification
gate, the rewritten rotation algorithm and its crash semantics, and the extended adversarial test
contract — including the same-predecessor dual-writer race under both orderings and every named
authority-rotation crash point — confirmed no regression in any previously-passing fencing,
reconciliation, or privilege control, confirmed GCP Secret Manager alone still does not qualify,
and found no remaining material architecture, concurrency, replay, fencing, recovery, or privilege
gap. Amendment 1 is Accepted (2026-08-14) on this basis. Target execution of the two P0
remediations it authorizes (replay-resistant recovery-freshness protocol; P0-1 exact
legacy-adoption validation, already required by accepted D-6) remains a separate, subsequent
implementation review; this acceptance does not itself authorize staging, commit, or RC.9 build.

Because source and release-gate behavior change, RC.9 must rebuild all eight governed images and
regenerate Trivy reports, CycloneDX SBOMs, GHCR digests, Cosign signatures, GitHub provenance,
image records, release manifest, resolved staging/production bundles, rollback bundle, and
repository qualification. ADR-043 is accepted and its implementation is committed
(`464496238103978ec422c5d833be2f1800747777`), adding the isolated Identity migration stream
(`V001__identity_refresh_state.sql`, `V002__identity_recovery_state.sql`). RC.9's governed
migration-set hash therefore **differs from RC.8's** and must be freshly generated and qualified
against the reconciled source commit; it must not be copied from RC.8 evidence or assumed
unchanged. The exact hash value is not invented here — it is produced only when the RC.9 release
workflow runs against the final reconciled commit.

RC.8 live observations may inform diagnosis but must not be relabeled as RC.9 qualification.

## Reconciliation checklist

| Evidence slot | Classification | Required fields | Status |
| --- | --- | --- | --- |
| Keycloak runtime health | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED / RC9_REQUALIFICATION_REQUIRED | endpoint/context, time, release, result, witness role | PENDING_LIVE |
| Realm import and client provisioning | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | realm/config identity, client IDs, mapper/flow result; no secrets | PENDING_LIVE |
| Token/claim qualification | RC9_REQUALIFICATION_REQUIRED | issuer, audience, tenant, roles, clearance, delegation attribution, negative cases | PENDING_LIVE |
| Authenticated Studio→BFF→KG→Audit | RC9_REQUALIFICATION_REQUIRED | browser route, exact release, correlation IDs, safe outcome, witness | PENDING_LIVE |
| TLS/DNS/ingress/egress | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | names, certificate fingerprint/dates, routes/policies, result | PENDING_LIVE |
| ExternalSecrets | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | SecretStore/reference readiness and workload consumption; no values | PENDING_LIVE |
| Cloud SQL databases/roles | RC9_REQUALIFICATION_REQUIRED | database/role names, effective attributes, isolation, bootstrap/migration result | PENDING_LIVE |
| Audit Projector | RC9_REQUALIFICATION_REQUIRED | runtime health/readiness, stable projector identity, Keycloak/service authentication as the intended projector client, database connectivity and least-privilege runtime role, `mutation_dispatch` consumption, Audit delivery, restart behavior, no duplicate replay of already-delivered events; retry/crash-recovery behavior only where a safe live fixture exists — RC.8 observations are diagnostic context only and do not qualify RC.9 | PENDING_LIVE |
| Knowledge Graph | RC9_REQUALIFICATION_REQUIRED | runtime health/readiness, Keycloak authentication, tenant/role claim enforcement, PostgreSQL connectivity and least privilege, HTTPS connectivity to Audit, governed mutation path, mutation → `mutation_dispatch` generation, projector/Audit downstream correlation, governed search, search-cursor qualification/round-trip where required; Neo4j projection/fallback behavior only if relevant to the current V1 contract (Neo4j is a rebuildable projection, not authoritative) — RC.8 observations are diagnostic context only and do not qualify RC.9 | PENDING_LIVE |
| NetworkPolicy activation | RC9_REQUALIFICATION_REQUIRED | policy inventory, allowed and denied probes, context | PENDING_LIVE |
| Alert routing/delivery | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | evaluator/receiver decision, rule load, fired/resolved delivery, acknowledgement | PENDING_LIVE |
| Backup/WAL custody | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | remote administrative separation, encryption/escrow IDs, schedule, retention safety | PENDING_LIVE |
| Restore/PITR | RC9_REQUALIFICATION_REQUIRED | isolated target, recovery point, measured RPO/RTO, integrity/reconciliation, witnesses | PENDING_LIVE |
| Rollback witness | RC9_REQUALIFICATION_REQUIRED | prior complete version/digests, chronology, migration hash, deploy/smoke/return result | PENDING_LIVE |
| Staging qualification | RC9_REQUALIFICATION_REQUIRED | manifest/bundle hashes, protected approval, stage results, smoke, witness | PENDING_LIVE |

### ADR-043 Identity recovery-governance evidence (new for RC.9)

None of the following existed at RC.8 and none may be satisfied by RC.8 evidence, local mocks, or
repository test coverage alone.

| Evidence slot | Classification | Required fields | Status |
| --- | --- | --- | --- |
| Identity live deployment | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | target namespace/cluster, release digest, deployment/rollout result | PENDING_LIVE |
| Identity production-mode readiness | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | `/healthz`/`/readyz` result, A8 recovery-gate pass, dependency readiness | PENDING_LIVE |
| Identity Keycloak HTTPS/JWKS authentication | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | issuer, JWKS endpoint, TLS result, signature/claim verification | PENDING_LIVE |
| Human tenant/classification claim qualification | RC9_REQUALIFICATION_REQUIRED | tenant, roles, clearance claim verification against the live realm | PENDING_LIVE |
| Identity session/refresh flow | RC9_REQUALIFICATION_REQUIRED | rotation, family revocation-on-reuse, single-use proof against live PostgreSQL | PENDING_LIVE |
| Identity Audit delivery | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | authentication-event delivery to Audit, correlation IDs | PENDING_LIVE |
| Stage-50 recovery-qualification mode | RC9_REQUALIFICATION_REQUIRED | `validate-recovery-qualification` run against a real recovery event; PASS/FAIL and references to the validated A9 evidence artifacts; the expected recovery fence owner supplied via `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_OWNER` and the expected namespace supplied via `EMG_IDENTITY_RECOVERY_FENCE_EXPECTED_NAMESPACE` (both independently supplied inputs — Stage-50 never trusts an evidence file's own claims); evidence that each A9 artifact's `verified_by` attribution was checked against, and matched, the expected fence owner, and that the network-fence evidence's namespace was checked against, and matched, the expected namespace; a wrong-owner or wrong-namespace evidence record demonstrably fails closed during this qualification where safely demonstrable; the actual recovery-coordinator identity and the actual target namespace the live qualification ran against, recorded in the RC.9 evidence record | PENDING_LIVE |
| Phase 1 network-fence live enforcement | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | read-back NetworkPolicy, additive-bypass scan result, migrator-only reachability proof | PENDING_LIVE |
| Phase 2 readiness-qualification fence live enforcement | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | reachability narrowed to only the fresh qualification workload; client-traffic fencing unchanged | PENDING_LIVE |
| `LIVE_CNI_ENFORCEMENT_WITNESS` | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | packet-level confirmation the target cluster's CNI enforces `NetworkPolicy` Egress; never inferred from the repository's schema/freshness-only qualification evidence | PENDING_LIVE |
| Database-session-fence live termination/reproof | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | `emg_identity_app` session termination and zero-survivor re-query against the recovery target | PENDING_LIVE |
| Approved Recovery Authority provider selection and live qualification | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | selected provider, A3 eight-property qualification-gate result, configured history retention | PENDING_LIVE |
| Authority rotation/replay-resistance witness | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | live rotation against the qualified provider; rollback/reuse-rejection proof | PENDING_LIVE |
| Target full-restore witness | RC9_REQUALIFICATION_REQUIRED | isolated target, full backup restore, integrity/schema/Audit/projection checks | PENDING_LIVE |
| Target PITR witness | RC9_REQUALIFICATION_REQUIRED | isolated target, point-in-time recovery, measured RPO/RTO | PENDING_LIVE |
| Restored refresh credential rejection | RC9_REQUALIFICATION_REQUIRED | post-reconciliation replay of a pre-restore refresh token/family fails | PENDING_LIVE |
| Recovery witness/fence-release approval | LIVE_EVIDENCE_FROM_CLAUDE_REQUIRED | named witness role approval of A9.6 steps 1-7 recorded before fence release | PENDING_LIVE |
| Final P0 closure | RC9_REQUALIFICATION_REQUIRED | four P0 results and accountable approvals | OPEN |

## RC.9 cut readiness

Before tag creation:

1. Preserve and separately identify Claude’s RC.8 evidence.
2. Review/merge this branch and record its commit(s).
3. Rebase/merge any approved live-environment repository changes without importing secret values.
4. Run all local/CI gates on the final commit.
5. The accepted ADR-043 implementation is included (`464496238103978ec422c5d833be2f1800747777`).
   Qualify the changed Identity migration set and reassess rollback/recovery compatibility against
   the reconciled source commit; do not assume the migration set is unchanged from RC.8.
6. Create RC.9 only through the governed tag workflow after explicit authorization.

`SAFE_TO_CUT_RC9` remains **NO** until this branch and Claude’s repository changes are reconciled,
merged, clean, and approved. `SAFE_TO_PROMOTE_PRODUCTION` remains **NO** until all P0 evidence is
PASS for RC.9.

## Post-v1

Full Decision Intelligence, AI orchestration, broad ingestion/API expansion, entity-resolution
ownership, multi-region HA/chaos automation, and documentation automation are `POST_V1`.
