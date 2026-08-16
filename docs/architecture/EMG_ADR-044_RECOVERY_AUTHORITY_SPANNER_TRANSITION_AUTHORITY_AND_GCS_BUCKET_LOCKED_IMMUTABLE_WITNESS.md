# EMG ADR-044 — Recovery Authority: Spanner Transition Authority and GCS Bucket-Locked Immutable Witness

**Status:** Proposed — pending independent architecture/security review
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** Not yet accepted
**Baseline:** `develop` at `8d66fc6442f6f2b49af9a8bc8cb1546f4fb4aeae`
**Related:** ADR-039 (Backup, PITR and Recovery Governance), ADR-040 (Runtime Image Supply
Chain), ADR-041 (Production Provisioning Ownership & Bootstrap Contract), ADR-043
(Identity Durable Refresh State Database and Migration Authority — a separate, disjoint
decision; see §16).

> **This ADR authorizes architecture only after acceptance.** It ratifies a design and a
> body of implementation and provider-qualification evidence that already exist in the
> repository; it does not itself grant production approval, does not authorize
> production deployment, does not create or modify any GCP resource, and does not
> unblock any Identity/RC.11 qualification path. See §22 (Production approval boundary)
> and §16 (Relationship to ADR-043).

---

## 1. Context

`services/recovery-authority` was added to `develop` starting at commit `20a2416`
("feat: add ADR-043 recovery authority foundation") and extended through commits
`167a4c8`, `c7c58d3`, `8fff95f`, and `8d66fc6`. Its own source comments, package
documentation, and README consistently describe it as implementing "the frozen ADR-043
architecture" and its cryptographic domain separators are literally named
`EMG-ADR043-PREPARED-V1`, `EMG-ADR043-COMMITTED-V1`, and similarly for every other
protocol record family.

No accepted architecture decision record for this design exists anywhere in the
repository. The repository's one Accepted "ADR-043" —
`EMG_ADR-043_IDENTITY_DURABLE_REFRESH_STATE_DATABASE_AND_MIGRATION_AUTHORITY.md`, plus
its Accepted Amendment 1 — governs a disjoint subsystem: Identity refresh-token durable
PostgreSQL state and a Vault-KV-v2/GCP-Secret-Manager-based "Approved Recovery
Authority" for anti-replay generation rotation. That document never mentions Spanner,
GCS, Bucket Lock, epoch, witness, or rotation-commit, and its own Scope section (D-2)
states it governs only Identity refresh-token placement, roles, schema, and recovery —
nothing else.

This gap was surfaced by an independent, read-only ADR-043 production-readiness review
(recorded as the governance finding motivating this document) after two real-GCP
provider-qualification trials were completed and committed as evidence:

- `services/recovery-authority/docs/evidence/adr-043/real-gcp-safe-qualification/`
- `services/recovery-authority/docs/evidence/adr-043/real-gcp-destructive-qualification/`

Both trials are real, hash-verified, sanitized evidence against a disposable Google
Cloud project (`emg-adr043-disposable-witness`) — never against `emg-platform-staging`
or any production resource. §11 and §12 of this ADR incorporate their findings.

## 2. Problem

Two problems require resolution, both governance/traceability problems, not defects in
the implemented code:

1. **No accepted decision record exists** for an architecture that a runtime security
   boundary, a signed cryptographic protocol, and two real-provider qualification
   trials were all built against, under the belief (asserted repeatedly in source
   comments) that it was already "frozen" architecture. Nothing was maliciously
   misrepresented — the commits describe exactly what they built — but no governance
   body ever reviewed or accepted the design itself.
2. **Numbering collision.** The label "ADR-043" is used by two unrelated systems in the
   same repository. This creates a real risk that an incident responder, auditor, or
   future engineer pulls the wrong governing document during a recovery event.

This ADR resolves problem 1 by formally ratifying (subject to independent review; see
§23) the architecture that has already been implemented and experimentally qualified.
It resolves problem 2 by claiming a new, distinct number — ADR-044 — determined from
the canonical index in `EMG_ARCHITECTURE_DECISION_REGISTER.md` (ADR-014 through
ADR-043 are present, ADR-031 is explicitly recorded absent; ADR-044 is the next
available number) rather than renumbering or amending the existing, unrelated ADR-043.

## 3. Security objectives

1. No single party's storage-administration capability may ever substitute for
   possession of the cryptographic signing authority.
2. Every accepted state transition must have exactly one authoritative linearization
   point, decided by a strongly consistent transition authority — never inferred
   after the fact from a later read.
3. Any transition whose outcome cannot be affirmatively proven successful must be
   treated as unresolved, never as either success or failure by default.
4. Loss of the in-process capability that proves a transition was genuinely accepted
   must be unrecoverable — a lost proof can never be reconstructed, only superseded by
   a fresh, independently re-established epoch.
5. The provider-durable rollback witness must be independently, cryptographically
   verifiable without trusting the storage provider, any storage administrator, or the
   mere existence of bytes at the expected location.

## 4. Decision

EMG adopts, as its recovery-authority architecture for the resource class this package
governs, exactly the two-provider design already implemented in
`services/recovery-authority`:

- **Google Cloud Spanner is the sole transition/CAS authority.** Every accepted state
  transition is decided at exactly one linearization point: a single Spanner `Commit`
  RPC, invoked over the raw `spannerpb.SpannerClient` interface (never the high-level
  GAX client, retrying transaction helpers, or multiplexed sessions), classified
  fail-closed by `rotationcommit.ClassifyCommit`.
- **Google Cloud Storage, under a locked Bucket Lock retention policy, is a passive
  immutable rollback witness only.** It is never consulted to decide whether a
  transition occurred; it only durably persists, and later proves the exact byte
  content of, an already-decided, already-signed record.
- **PostgreSQL is not the transition authority for this design and is out of scope of
  this ADR entirely.** No table, schema, or role introduced by ADR-043 (Identity) or
  any other accepted ADR is read, written, or referenced by this architecture.

## 5. Authority model

Spanner's `Commit` RPC is the only mechanism by which a proposed state transition
becomes accepted. `rotationcommit.ClassifyCommit` (`internal/authority/rotationcommit/classifier.go`)
enforces a strict three-way, fail-closed classification of every commit attempt:

- **`UnambiguousSuccess`** — commit not invoked is impossible by definition here; this
  requires a structurally valid, strictly-positive `CommitTimestamp` with no error. A
  zero or negative timestamp — which official Spanner documentation never states is a
  valid successful-commit value — is deliberately treated as ambiguous, not success.
- **`UnambiguousNotCommitted`** — an explicit `codes.Aborted`, a commit never invoked,
  or the defensive "precommit token" case (an unsupported session profile) — all safe
  to retry the identical operation from an unchanged predecessor.
- **`AmbiguousCommitOutcome`** — the default for anything not affirmatively classified
  above, including any transport/network/deadline failure. Ambiguity is never resolved
  by re-reading Spanner state after the fact; the classification is made once, from the
  attempt's own response, and never revisited.

`epoch.State` (`internal/authority/epoch/state.go`) models the resulting security state
purely from `protocol.CommitOutcome` values, with no provider dependency of its own.
`StateUnresolvablePreparedOperation` is the zero value — the safest possible default —
and only `StateActive` permits any authority-dependent decision (`RecoveryAllowed`,
`RotationAllowed`, `FenceReleaseAllowed`, `PostgreSQLReconciliationAllowed`). A
`Commit` classified `UnambiguousSuccess` moves the epoch to
`StateRecoveryFrozenPendingWitness` — never directly to `Active` — until the
same-operation `COMMITTED` witness write itself completes and validates
(`TransitionOnWitnessOutcome`).

## 6. Witness model

`gcswitness.Adapter` (`internal/authority/gcswitness/gcswitness.go`) is the sole GCS
integration point and exposes exactly three operations: `CreateExactIfAbsent`,
`ReadExact`, `Exists`. No `Delete`, `Update`, `Compose`, `Copy`, ACL, or
retention-mutation method exists anywhere in the package; no `*storage.Client`,
`*storage.BucketHandle`, or `*storage.ObjectHandle` ever leaves the package boundary.

**Create-if-absent, no overwrite, no delete-to-retry, no alternate-key fallback.**
`CreateExactIfAbsent` writes using `storage.Conditions{DoesNotExist: true}` — wire
`ifGenerationMatch=0` — with `Writer.ChunkSize = 0` (a single, non-resumable,
SDK-non-retryable request). It never regenerates or transforms the payload, never
internally retries `Writer.Close`, and never creates a second key on conflict.

**Ambiguous-write resolution through exact read only.** A 412 (precondition failed) or
any other non-definitive failure is resolved, and only resolved, by an exact-key read
(`ReadExact`, never LIST) compared byte-for-byte against the exact bytes the call
itself attempted to write:

- Existing bytes identical to what was attempted → `CreateSuccess` (ambiguous transport
  failure, own write already durable) or `AlreadyExistsIdentical` (genuine 412) — both
  safe, idempotent outcomes.
- Existing bytes different → `AlreadyExistsConflict`, a fail-closed condition; the
  caller must never treat this as success, overwrite, or fall back to an alternate key.
- A hard, definitive failure (400/401/403/404) is never sent through read-resolution.

**GCS create-ambiguity and Spanner Commit ambiguity are two deliberately different
classes and must never be conflated.** They are resolved by different rules because they
protect different things:

- **Spanner Commit ambiguity (§5, §8).** A later read MUST NEVER resolve acceptance
  provenance. Matching Spanner state does not, and cannot, establish that the original
  authorized CAS attempt actually committed — no read, of any kind, against any system,
  is ever permitted to convert an ambiguous Commit outcome into a resolved one. Ambiguity
  here always routes through the existing fail-closed epoch behavior
  (`StateUnresolvablePreparedOperation` → `NEW_EPOCH_REQUIRED`, §8), never through a
  read.
- **GCS create-ambiguity (this section).** By the time a `CreateExactIfAbsent` call is
  even attempted, acceptance provenance has *already* been established — the bytes being
  written are the already-signed `CommittedPayload` produced from a live
  `acceptedRotationContext` (§7, §9). A later exact-key GCS read at this stage resolves
  only whether *that already-decided, already-signed object* was durably persisted — it
  never creates, infers, or reconstructs acceptance provenance, because the provenance
  question was already closed before this call began. This is why exact-key
  byte-comparison is a safe resolution technique here and is never a safe resolution
  technique for Spanner Commit ambiguity: the two ambiguities sit on opposite sides of
  the point where provenance is established.

**Exact-key read resolution is therefore permitted for GCS witness-create ambiguity
only. It remains categorically prohibited for Spanner Commit ambiguity**, regardless of
how the read is performed, what it matches, or how soon after the attempt it occurs.

Bucket Lock's provider-level guarantee — that not even the bucket or project owner can
alter a locked retention policy before its expiration — was independently confirmed
against a real, disposable GCP project in both qualification trials (§11).

## 7. Cryptographic provenance model

**`CONTENT_BINDING != ACCEPTANCE_PROVENANCE`.** A persisted GCS object never, by
itself, establishes that the record it contains was genuinely produced by the
authorized Spanner-accepted transition. Two independent, both-mandatory checks are
required before any `CommittedPayload` may be trusted (`recovery/committed_verification.go`,
`VerifyPersistedCommitted`):

1. **Content binding** — the payload's own bound fields (`EnvironmentID`,
   `AuthorityEpoch`, `ResourceIncarnationID`, `OperationID`, `PredecessorRevision`,
   `PredecessorDigest`) must exactly equal what the caller independently expected.
2. **Acceptance provenance** — a non-empty writer signature must verify, using
   verify-only key material, against a digest the verifier itself recomputes from the
   payload's bound fields (`CanonicalDigest`) — the payload's own self-reported digest
   is never trusted.

A payload that binds correctly but carries no valid signature fails exactly as hard as
one with a valid-looking signature over the wrong content. Neither property alone is
sufficient. A storage or cloud administrator who can create arbitrary bytes at the
exact expected key still cannot produce a validly-signed `CommittedPayload` without the
private signing key.

**No private signing key crosses the recovery boundary.** `rotationcommit.Signer` is an
interface only; no concrete implementation exists anywhere in this repository. The sole
call site that invokes it (`buildCommittedPayload`) is unexported and requires a live
`acceptedRotationContext` — an unexported type, constructible only inside
`completeRawCommit`, as the direct, same-operation result of a `Commit` classified
`UnambiguousSuccess`. The `recovery` package holds only `CommittedSignatureVerifier` —
a verify-only interface that can prove a signature valid but can never produce one.

**`acceptedRotationContext` cannot be reconstructed after loss.** Its `capability`
field is a package-private `processCapability` wrapping a non-comparable function
value, deliberately making the type impossible to serialize, marshal, or reconstruct by
any code outside `rotationcommit`, including recovery code, including this same process
after a restart. Loss of this value is unrecoverable by design; the only path forward
is a fresh epoch (§8).

## 8. State-machine and fail-closed requirements

`NEW_EPOCH_REQUIRED` (`epoch.State.NewEpochRequired()`) is true exactly for
`StateUnresolvablePreparedOperation` and `StateEpochTerminated`, and
`TransitionOnCASOutcome` routes any Spanner outcome other than `UnambiguousSuccess` /
`UnambiguousNotCommitted` — including every ambiguous or unrecognized outcome — to
`StateUnresolvablePreparedOperation`. No authority-dependent decision (recovery,
rotation, fence release, or any future PostgreSQL-side reconciliation this design might
someday support) may be made from an epoch in this state or in
`StateEpochTerminated`. This mandatory behavior is unchanged by this ADR and MUST NOT
be weakened by any future amendment without a separately reviewed, explicit decision.

## 9. Process-loss behavior

Genuine process loss (crash, restart, replacement) after a `Commit` is classified
`UnambiguousSuccess` but before the same-operation `COMMITTED` witness write completes
leaves the epoch in `StateRecoveryFrozenPendingWitness` with no live
`acceptedRotationContext` — that value cannot survive a process boundary by
construction (§7). No code path in this repository reconstructs, infers, or fabricates
a replacement `acceptedRotationContext.` The only defined recovery from this state is
the governed `NEW_EPOCH_REQUIRED` procedure (§8): the old epoch is formally terminated
(`epoch.Terminate`, requiring the caller to have already recorded an
`AmbiguousOperationTombstone` and `EpochTerminationRecord` as evidence) and a genuinely
new epoch is established. Failure-injection and emulator-tier process-kill tests
(`failure_injection_test.go`, `emulator_processkill_test.go`) exercise this behavior at
the unit/emulator level; real-Spanner process-loss qualification has not yet been
performed (§21).

## 10. Terminology note — historical "ADR-043" identifiers

Every reference to "ADR-043" inside `services/recovery-authority` — including package
doc comments, the service README, and the cryptographic domain separators
`EMG-ADR043-PREPARED-V1`, `EMG-ADR043-COMMITTED-V1`, `EMG-ADR043-AMBIGUOUS-TOMBSTONE-V1`,
`EMG-ADR043-EPOCH-TERMINATION-V1`, `EMG-ADR043-NEW-EPOCH-GENESIS-V1`,
`EMG-ADR043-AUTHORITY-STATE-V1`, and `EMG-ADR043-ROTATION-CANDIDATE-V1`
(`internal/authority/protocol/canonical.go`) — reflects the historical working
identifier used during implementation, before this governance collision was
discovered. **This ADR is the actual governing decision record for this architecture;
the identifier "ADR-043" appearing throughout the package does not indicate, and never
indicated, that this design was reviewed or accepted under the Identity ADR-043.**

**The cryptographic domain separators are retained unchanged in this ADR.** They are
protocol-significant: each is mixed into `HashCanonical`'s digest computation for its
record family, and changing any one of them would change every digest computed from
it — a protocol-breaking change that could invalidate the meaning of any future
persisted `PREPARED`/`COMMITTED` record and would need its own separately reviewed
protocol-migration decision, not a documentation renumbering. They are not renamed by
this ADR.

Source comments and the service README's use of "ADR-043" are purely descriptive and
carry no independent decision authority (consistent with GR-001 Rule 3 — a citation
confers no authority; the cited document's own status does). They are not modified by
this ADR. A future, separately-scoped, documentation-only change may update these
comments to cite ADR-044 explicitly; that is deferred as an unnecessary diff surface
against a security-sensitive package for this governance-only decision, and is not
required for this ADR to take effect. The full occurrence inventory and classification
supporting this determination is recorded in Appendix A.

## 11. GCS Bucket Lock qualification (evidence)

Findings from `real-gcp-safe-qualification/` and `real-gcp-destructive-qualification/`
(both against disposable project `emg-adr043-disposable-witness`; neither ever touched
`emg-platform-staging` or any production resource):

- A 1-second retention period was accepted by the **safe-qualification trial**
  specifically (`real-gcp-safe-qualification/`), for rapid iterative testing of
  enforcement behavior. The **destructive trial** (`real-gcp-destructive-qualification/`)
  used a materially longer, 86400-second (24-hour) retention period instead, so that a
  meaningful active-retention window persisted across the full delete/restore cycle
  (§12–§13). The two trials' retention periods are not interchangeable evidence; where a
  finding below applies to only one trial, that trial is named. Production retention
  periods are a separate, unresolved configuration decision — see §21.
- Bucket Lock successfully locked the retention policy (`isLocked: true`).
- Retained-object overwrite was rejected.
- Retained-object deletion was rejected.
- Locked-retention-period reduction was rejected.
- Locked-retention-policy removal was rejected.
- Deletion of a non-empty locked bucket was rejected.
- Bucket Lock generated a Resource Manager project-deletion lien
  (`resourcemanager.projects.delete` restriction, origin `storage.googleapis.com`).
- Project deletion with the lien present was rejected.
- Lien removal did **not** weaken object-level retention enforcement — a delete attempt
  immediately after lien removal still returned `403 / retentionPolicyNotMet`.
- Project deletion after lien removal transitioned the project to `DELETE_REQUESTED`.
- Project restoration (`projects.undelete`) returned the project to `ACTIVE`.
- The original bucket survived, byte-identically (confirmed by matching metadata
  hashes across pre-lock, pre-deletion, and post-restore reads).
- The original object survived.
- Object generation remained identical (`1786901627964283`).
- SHA-256 remained identical (independently recomputed from downloaded bytes, not
  merely accepted from provider metadata).
- CRC32C remained identical (provider-reported).
- MD5 remained identical (provider-reported).
- Retention period survived unchanged (86400s in the destructive trial).
- Retention effective time survived unchanged.
- Object retention expiration survived unchanged.
- Bucket Lock state survived unchanged (`isLocked: true`).
- Post-restore deletion remained blocked (`403 / retentionPolicyNotMet`) while
  retention remained active — the decisive proof point of the destructive trial.

**Qualification billing-account topology (disclosed, not merely inferable).** Both
trials' disposable project used Cloud Billing account `01CDA5-613648-B7B26E` — the
**same billing account already used by `emg-platform-staging`**. This sharing is
recorded explicitly in the safe-qualification evidence README's own "Isolation" row as
having been "explicitly waived by the requester for this SAFE phase only." The staging
project's own resources were never accessed, modified, or read by either trial (verified
independently in both evidence packages' isolation statements). This fact:

- does **not** invalidate the Bucket Lock survival evidence above — retention
  enforcement, generation identity, and byte identity are bucket/object-level GCS
  properties, wholly independent of which billing account is attached;
- **does** mean neither trial tested billing-account isolation — the qualification
  environment's own billing coupling with staging was never exercised as a variable, and
  no conclusion about safe or unsafe billing-account sharing can be drawn from either
  trial;
- **does** demonstrate that billing-account coupling between a Recovery Authority
  project and another critical EMG environment is a real, already-manifested condition
  in this repository's own qualification history — not a purely hypothetical governance
  scenario. See §17 item 8 for the resulting production requirement.

**`BLOCKER_A_EXPERIMENT_RESULT = SURVIVED_PROJECT_DELETE_RESTORE`**
**`BLOCKER_A_STATUS = EXPERIMENTALLY_PASSED`**
**`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED`**

This is a single-trial, single-project, single-billing-account experimental result. It
is not converted here into a universal Google Cloud guarantee, and it does not by
itself establish organization-boundary, cross-project, or cross-billing-account
behavior (§13, §21).

## 12. Project lifecycle qualification

Covered fully in §11. Summarizing the state transitions proven: `ACTIVE` (locked,
lien present) → lien removed → `ACTIVE` (still enforced) → `DELETE_REQUESTED` →
`ACTIVE` (restored) → billing-disabled (see §13) → billing re-linked → object readable,
byte-identical, still retention-protected.

## 13. Billing lifecycle dependency

**Discovered finding:** `projects.undelete` restored `lifecycleState = ACTIVE` but did
**not** automatically restore the Cloud Billing association. Cloud Storage object-level
access remained unavailable (`403: The billing account for the owning project is
disabled in state absent`) until the project's previously approved billing account was
explicitly re-linked (`gcloud billing projects link`).

**Classification: OPERATIONAL RECOVERY DEPENDENCY.** Not data loss — object bytes,
generation, hash, retention, and lock state were all confirmed unchanged throughout the
billing-disabled window. Not protocol authority — nothing about Spanner's transition
authority or GCS's witness role changes because of this finding; it is an availability
dependency in the surrounding provider environment, not a defect in either provider
component this ADR governs.

**Required recovery sequence:**

```
PROJECT RESTORE
  -> VERIFY PROJECT lifecycleState = ACTIVE
  -> VERIFY BILLING ASSOCIATION
  -> RE-LINK ONLY THE PREVIOUSLY APPROVED BILLING ACCOUNT IF REQUIRED
  -> VERIFY billingEnabled = true
  -> VERIFY EXPECTED BUCKET IDENTITY
  -> VERIFY BUCKET LOCK/RETENTION STATE
  -> READ EXACT WITNESS KEY
  -> CRYPTOGRAPHICALLY VERIFY SIGNED COMMITTED
  -> VERIFY ENVIRONMENT/EPOCH/RESOURCE/OPERATION/PREDECESSOR BINDINGS
  -> ONLY THEN ALLOW THE EXISTING RECOVERY STATE MACHINE TO DETERMINE
     WHETHER RECOVERY MAY PROCEED
```

**Explicitly prohibited**, under any circumstance, as a recovery technique:

- recreating a missing witness;
- creating a replacement bucket;
- using a different object/key;
- manually signing a `COMMITTED` payload;
- reconstructing `acceptedRotationContext`;
- treating object presence alone as acceptance provenance;
- bypassing signature verification;
- bypassing binding verification;
- shortening retention as a recovery technique;
- removing retention as a recovery technique.

This sequence and its prohibitions must be lifted into a standalone production
operations runbook before production deployment (§21); today it exists only inside
this ADR and the destructive-qualification evidence README.

## 14. Threat model

| Actor capability | Cryptographic integrity | Provider immutability | Availability | Administrative governance |
| :--- | :--- | :--- | :--- | :--- |
| **A.** Write witness objects | Protected — create-if-absent + fail-closed conflict handling; any written bytes still require a valid signature to be trusted | — | — | — |
| **B.** Administer the bucket | Protected — cannot forge a signature | Bucket Lock defends the object itself (evidenced) | — | Governance boundary: bucket admin should not be the runtime principal (§15) |
| **C.** Administer the project | Protected — cannot forge a signature | Locked retention specifically survives project-admin-level reduction/removal attempts (evidenced) | — | Governance boundary (§15) |
| **D.** Remove Resource Manager liens | — | Proven empirically insufficient alone — object-level enforcement was unaffected (evidenced) | — | Lien removal must not be a normal runtime capability (§15) |
| **E.** Delete/restore the project | — | Content/retention proven to survive in this trial (evidenced) | Requires also holding lien-removal capability, which production must not grant to the runtime identity | — |
| **F.** Modify billing association | Unaffected | Unaffected | **This is the vector** — proven to be an availability/denial-of-service concern only (§13) | Billing relink must be an exceptional, separately governed action (§15) |
| **G.** Control the cloud organization | **NOT fully mitigated unless the signing trust domain is administratively independent (see §15A).** A forged `COMMITTED` payload requires the signing key, but if that key's IAM, or the workload/service-account that invokes it, remains administratively reachable by the same organization administrator being modeled here, that administrator can self-grant signing permission, impersonate the signing principal, or redeploy the signing workload — collapsing the boundary. KMS custody alone does not establish this independence. | Not defensible at this level by any application-layer control | Not defensible at this level | Open until §15A is implemented and qualified; organizational trust boundary |
| **H.** Provider/operator-level failure | Mitigated only by independent hash re-verification (never trusting provider-reported hashes alone), already exercised in evidence | **Not claimed** — Bucket Lock does not protect against every provider/operator failure | Not defensible at this level by this architecture | Out of scope of this ADR |

This ADR does not claim Bucket Lock protects against every provider or operator-level
failure (row H); it claims specifically what §6 and §11 establish, and no more. **Row G
is deliberately not framed as a defended threat.** An organization administrator who
also administers the signing trust domain can defeat the cryptographic provenance
model entirely; §15A defines the required, currently unimplemented, independence
property that would close this gap, and §17 records its implementation and
qualification as a production blocker, not an optional hardening step.

## 15. IAM separation (required for future production implementation)

No IAM design or manifest exists yet for this service — no deployable binary, no
`infra/` entry. This section is a required design constraint for when that
implementation begins, not a description of anything currently deployed. Logical
capabilities, to be separated by distinct principals:

- **Witness writer** — `CreateExactIfAbsent` only, on the specific bucket/prefix.
- **Witness reader/verifier** — read-only (`ReadExact`/`Exists`) on the same
  bucket/prefix; may reasonably share a runtime principal with the witness writer, both
  being narrow, non-destructive, adapter-enforced operations.
- **Signing authority** — holds or invokes the private signing key (future KMS
  integration). Must be separately controlled from every other capability below.
- **Retention-policy administrator** — sets/locks the bucket's retention policy. A rare,
  governance-controlled, one-time-per-bucket action, not a runtime capability.
- **Lien modifier** — removes/manages Resource Manager liens.
- **Project administrator** — general project-level administrative authority.
- **Billing relinker** — re-links a project's billing association.
- **Recovery operator** — the human/process actually executing a project
  restore/billing-relink during an incident; a distinct, ideally break-glass/
  just-in-time, audited principal.

**The normal Recovery Authority runtime principal MUST NOT possess:** lien-removal
permission, project-deletion permission, billing-link permission, retention-policy
administration, or organization administration. **The witness/recovery runtime MUST NOT
possess private signing authority** — this is not merely a recommendation but the
direct operational consequence of §7's `CONTENT_BINDING != ACCEPTANCE_PROVENANCE`
principle: a runtime that could both write witness bytes and sign them would collapse
the very separation that principle exists to guarantee.

**Billing relinking and lien modification must each be exceptional, separately governed
disaster-recovery actions** — evidenced directly by this project's own qualification
history: both were performed as narrowly-scoped, explicitly authorized, human-directed,
one-off actions outside any automated runtime path, never as the Recovery Authority's
own capability.

This section deliberately does not invent specific GCP IAM role names beyond what is
already verified from this session's real-provider evidence (e.g., the observed
`resourcemanager.projects.delete` lien restriction, `billing.resourceAssociations`-class
operations, and `storage.objects`/`storage.buckets` operations already exercised). Exact
role bindings are an implementation task for §21, not a decision this ADR makes.

### 15A. Signing administrative independence requirement

§15 establishes **runtime separation** — the signing authority is a distinct logical
principal from the witness writer/reader, retention administrator, lien modifier,
project administrator, and billing relinker. Runtime separation is necessary but **not
sufficient**: it says nothing about who can *administer* the signing authority itself.
This subsection establishes the second, independent property required to make §14 row
G's threat actually defended, rather than merely asserted.

**Formal requirement — `SIGNING_ADMINISTRATIVE_INDEPENDENCE_REQUIREMENT`.** If the
architecture's threat model includes compromise of the organization administrator who
administratively contains the Spanner transition authority and the GCS witness (row G),
then the signing authority — its key material, its IAM policy, and the workload or
service identity permitted to invoke it — SHALL exist in an administratively
independent trust domain from that organization administrator's reach. Specifically:

1. Authority/witness administrators (anyone who can administer the Spanner project, the
   GCS witness project or bucket, or their IAM) must not be able to self-grant, or grant
   to any principal they control, signing capability.
2. Signing administrators (anyone who can administer the signing key or its invoking
   workload) must not be able to mutate Spanner authority state or GCS witness state.
3. The signing workload's deployment/runtime identity and the signing key's IAM policy
   must not both be governed by the single administrative authority modeled as
   compromised in threat-model row G — granting either one to that authority is
   sufficient to defeat this requirement; both must be kept out of reach.
4. Any break-glass path that can grant signing capability to a new principal SHALL
   require independent governance/approval distinct from ordinary Spanner/GCS
   administrative authority, and SHALL be auditable.
5. **Production approval SHALL remain blocked until a concrete implementation of this
   independent trust boundary is separately reviewed and qualified** (§17 item 9).

**KMS custody alone does not satisfy this requirement.** Using a managed KMS product is
an implementation detail of *where* the key material lives; it says nothing about *who*
can administer access to it. A KMS key sitting inside the same GCP organization, project
hierarchy, or IAM-admin scope as the Spanner/GCS resources it is meant to protect does
not satisfy `SIGNING_ADMINISTRATIVE_INDEPENDENCE_REQUIREMENT`, regardless of how
carefully its *runtime* invocation is scoped.

**This ADR does not select a specific realization.** Acceptable architecture-level
approaches — none selected, none excluded, none authorized for implementation by this
ADR — include: a separate GCP organization with independently governed IAM for the
signing trust domain; an external HSM or signing service under independent
administrative control (outside the GCP organization entirely); or another equivalent,
independently-governed cryptographic trust domain meeting the five properties above. The
repository has not selected one of these, and this ADR does not choose on its behalf —
that remains a separate, subsequent implementation-review decision (§17 item 9).

**Same-organization deployment is not ruled out**, but it is only acceptable if whatever
concrete signing trust boundary is eventually implemented still satisfies properties 1–4
above *within* that single organization (for example, through an org-policy-enforced,
separately-owned folder or project whose IAM the Spanner/GCS administrators cannot
reach). Same-org placement is not declared unsafe by this ADR, and it is not declared
safe either — it is unresolved until a concrete implementation is qualified against this
requirement.

## 16. Relationship to ADR-043 (Identity)

This ADR does **not** amend, supersede, weaken, or modify
`EMG_ADR-043_IDENTITY_DURABLE_REFRESH_STATE_DATABASE_AND_MIGRATION_AUTHORITY.md` in any
way. That document remains a wholly separate, Accepted (Amendment 1: Accepted
2026-08-14) architecture decision governing Identity refresh-token PostgreSQL state and
its own, independent "Approved Recovery Authority" concept (satisfied by Vault KV v2 or
a conditionally-qualified GCP Secret Manager pairing) for anti-replay generation
rotation. This ADR's byte content is unmodified by this decision.

**This ADR does not claim, and does not establish, that the Spanner/GCS Recovery
Authority described here is, or automatically becomes, the Identity ADR-043's "Approved
Recovery Authority."** That is a separate, unmade integration decision. Architecturally,
GCS Bucket Lock does not fit Identity ADR-043 Amendment 1's capability-2/3 requirements
(a monotonically-versioned, CAS-rotatable single object) — Bucket Lock is immutable
retained-object storage, not a version-counter authority. Spanner might satisfy
Amendment 1's mechanism 3a (native atomic conditional writes) if formally evaluated
against that ADR's eight-property authority qualification gate, but Amendment 1's
accepted text evaluates only Vault KV v2 and GCP Secret Manager and explicitly declines
to select a provider. Any future proposal to use this ADR's Spanner authority as
Identity ADR-043's Approved Recovery Authority requires its own separate, independent
architecture/security review against that ADR's qualification gate — it is not
authorized, implied, or shortcut by this ADR's acceptance.

This ADR's acceptance provides **no** basis to fabricate or manually bootstrap any
Identity `identity_recovery_state` row, UUID, revision, epoch, or witness record, and
does not unblock RC.11 or any Identity staging-qualification path. That path's
legitimate next step remains, independently, provisioning a real Approved Recovery
Authority under Identity ADR-043 Amendment 1's own accepted procedure.

## 17. Production prerequisites (not authorized or performed by this ADR)

Experimental provider qualification (§11) does not mean this service is
production-ready. The following components do not yet exist in this repository and are
recorded here as implementation/qualification work that may follow this ADR's
acceptance — none of it is implemented, authorized, or begun by this ADR itself:

1. A production Spanner adapter (only a test/emulator-only fake exists,
   `internal/authority/conformance/spanneradapter`, explicitly marked "not a production
   adapter").
2. A production Signer/KMS adapter (interface only today).
3. A deployable Recovery Authority binary/service entrypoint (no `main.go`/`cmd/`
   exists anywhere in the service).
4. Production IAM design and manifests implementing §15 (runtime separation) and §15A
   (signing administrative independence).
5. A governed Recovery Authority bootstrap/provisioning mechanism (none exists; no CLI,
   no infra manifest).
6. A standalone production recovery runbook (currently only embedded in this ADR and
   in the destructive-qualification evidence README).
7. Real-Spanner process-loss/crash qualification (currently only emulator-tested; see
   §9).
8. Resolution of the organization/billing-account boundary decision for the production
   witness project (§21). Not established as cryptographically required by current
   evidence — Bucket Lock enforcement and byte/generation survival are independent of
   billing-account placement (§11) — but a **separate billing account is the
   recommended default isolation / blast-radius control**, precisely because the
   qualification trials themselves were run under a billing account shared with
   `emg-platform-staging` (§11), demonstrating this coupling is a real condition, not a
   hypothetical one. If the production witness project is deliberately placed under a
   billing account shared with another critical EMG environment, that SHALL be an
   explicit, recorded risk-acceptance decision, never an accidental default inherited
   from qualification-environment convenience.
9. **Implementation and independent qualification of the `SIGNING_ADMINISTRATIVE_INDEPENDENCE_REQUIREMENT`
   (§15A).** This is a production blocker, not an optional hardening step: until a
   concrete signing trust domain satisfying §15A's five properties is implemented and
   separately reviewed, §14 row G's organization-administrator threat remains open, and
   production approval SHALL NOT be granted regardless of how complete every other item
   in this list is.
10. **KMS/signing-key lifecycle policy**, documented and tested, covering at minimum:
    key creation/provisioning; key activation; signer authorization; rotation; multi-key
    verification during and after rotation; compromised-key response; revoked-key
    handling; lost/unavailable-key handling; retirement/destruction timing; evidence
    retention dependencies; audit logging; break-glass use; and requalification after
    any key-policy or signer-implementation change. **Critical invariant this policy
    must preserve: historical, validly-signed `COMMITTED` records must remain
    independently verifiable after the signing key rotates.** A "verify against the
    current key only" design is insufficient — `CommittedSignatureVerifier` (§7) must
    either retain enough key-identifying metadata to select the correct historical
    verification key for a given record, or rely on another explicitly-qualified
    mechanism providing equivalent historical verification. This ADR does not design
    the concrete key-identifier format or rotation mechanism; it requires that whichever
    concrete design is proposed be reviewed against this invariant before production
    approval.

## 18. Evidence references

- `services/recovery-authority/docs/evidence/adr-043/real-gcp-safe-qualification/` —
  non-destructive Bucket Lock enforcement qualification (retention lock, overwrite/
  delete/retention-reduction/removal rejection, lien discovery).
- `services/recovery-authority/docs/evidence/adr-043/real-gcp-destructive-qualification/` —
  destructive project-delete/restore qualification (§11, §13).

**These directory paths are retained unchanged by this ADR.** Per the instruction
governing this document's creation, historical evidence paths are not renamed or moved
merely for cosmetic numbering consistency; doing so would rewrite evidence provenance
for no security or correctness benefit. **The `adr-043` segment in each path reflects
the historical working identifier used before this governance collision was
discovered** (§10) — it does not indicate, and must not be read as indicating, that
this evidence was collected in support of a review or acceptance of the Identity
ADR-043. This ADR (ADR-044) is the governing decision record these evidence packages
support.

## 19. Rejected alternatives

- **Amend the existing Identity ADR-043 to also cover this architecture.** Rejected:
  the two subsystems share no schema, role, provider, or protocol; conflating them in
  one document would violate the Identity ADR-043's own explicit non-supersession
  scope (D-2) and would make a security-critical document harder to review, not
  easier.
- **Renumber/rename the code's "ADR-043" identifiers to "ADR-044" immediately, including
  the cryptographic domain separators.** Rejected: the domain separators are
  protocol-significant (§10) — changing them is a protocol-breaking action requiring
  its own separately reviewed migration decision, not a side effect of a documentation
  governance fix. Renaming only the descriptive comments while leaving the wire
  constants unchanged would create a *worse* traceability trap (comments citing one
  ADR, wire bytes citing another) than the current, at least internally consistent,
  state.
- **Rename or move the evidence directories out of the `adr-043` path.** Rejected: this
  would rewrite historical evidence provenance for a cosmetic numbering concern; §18
  documents the historical meaning of the path instead.
- **Declare this ADR Accepted immediately, since the architecture is already built and
  experimentally qualified.** Rejected: the repository's own established governance
  convention for security-critical distributed-systems decisions (most directly, the
  Identity ADR-043 Amendment 1, which required five independent reviews before
  acceptance) requires independent review before Accepted status; the volume and
  security sensitivity of the invariants this ADR ratifies (§5–§9) warrant the same
  rigor, not a lesser standard merely because implementation happened first.
- **Treat Blocker A's experimental pass as sufficient for production approval.**
  Rejected explicitly — see §22.

## 20. Consequences

- The Spanner-sole-authority + GCS-Bucket-Lock-witness architecture gains a real,
  named governing decision record, closing the traceability gap identified by the
  production-readiness review.
- The ADR-043 label collision is resolved going forward: new references to this
  architecture should cite ADR-044; existing in-repository "ADR-043" references inside
  `services/recovery-authority` are documented as historical (§10) rather than silently
  renamed.
- No code behavior changes. No cryptographic constant changes. No test is weakened. No
  evidence artifact is altered.
- The Identity ADR-043 remains completely untouched and fully authoritative within its
  own, separate scope.
- A clear, explicit list of remaining production prerequisites (§17) now exists as a
  ratified reference point for future implementation work, rather than being scattered
  across review findings.

## 21. Non-goals

This ADR does not: authorize production deployment; create, modify, or delete any GCP
resource; implement a production Spanner or Signer/KMS adapter; define exact GCP IAM
role bindings; select or implement a specific realization of the signing
administrative-independence trust domain required by §15A (separate organization,
external HSM, or otherwise); resolve the production witness project's
organization/billing-account placement; declare same-organization deployment either
safe or unsafe (§15A); establish that Bucket Lock protects against every provider or
operator failure; extend or amend the Identity ADR-043; establish this architecture as
Identity ADR-043's Approved Recovery Authority; or unblock any Identity/RC.11 bootstrap
path.

## 22. Production approval boundary

**`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED.`** This ADR's acceptance — once
independently reviewed — ratifies the architecture and its experimental qualification
evidence; it is not, and must never be read as, a production approval decision.
Production approval requires, at minimum, every item in §17 to be independently
implemented and qualified, plus a separate, explicit production-approval decision
after that work is reviewed. Blocker A passing experimentally (§11) is one data point
supporting eventual production approval, not a substitute for it.

## 23. Acceptance gate

Before this ADR may be marked Accepted, an independent architecture/security review
SHALL confirm: the authority model and fail-closed classification (§5, §8); the witness
model's create-if-absent/no-overwrite/no-fallback/ambiguous-resolution semantics and the
explicit, non-symmetric distinction between GCS create-ambiguity and Spanner Commit
ambiguity (§6); the content-binding/acceptance-provenance separation and
no-private-key-crossing guarantee (§7); process-loss behavior and the
non-reconstructibility of `acceptedRotationContext` (§9); that no cryptographic domain
separator or serialized format was altered by this ADR (§10, Appendix A); the
qualification evidence, its scope limits, and its disclosed billing-account topology
(§11–§13); the threat model's honesty about what is and is not defended at each layer,
**including that row G is correctly left open rather than claimed as defended** (§14);
the IAM runtime-separation requirements (§15) **and the signing
administrative-independence requirement** (§15A); the explicit, unweakened boundary with
Identity ADR-043 (§16); and the completeness of the production-prerequisite list,
**including the signing trust-domain qualification and KMS key-lifecycle items** (§17).
This mirrors the rigor the repository's own governance convention already applied to
Identity ADR-043 Amendment 1.

---

## Appendix A — Traceability of existing "ADR-043" references in `services/recovery-authority`

Produced by a repository-wide search at this ADR's drafting baseline
(`8d66fc6442f6f2b49af9a8bc8cb1546f4fb4aeae`). No file listed below was modified by this
ADR.

| Classification | Where | Examples | Disposition |
| :--- | :--- | :--- | :--- |
| **A — cryptographic/protocol-significant wire constant** | `internal/authority/protocol/canonical.go` | `DomainPrepared = "EMG-ADR043-PREPARED-V1"` and six sibling `DomainSeparator` constants | **Not changed.** Mixed into every record family's canonical digest; changing any value is a protocol-breaking action requiring its own separately reviewed migration, per §10 and §19. |
| **A (bounded) — test-harness inter-process contract, not evidence-facing** | `internal/authority/rotationcommit/emulator_processkill_test.go` | `helperEnvMode = "EMG_ADR043_HELPER_MODE"` and twelve sibling env-var name constants | **Not changed.** Internal to a test binary's own subprocess protocol; touches no persisted artifact or evidence. Left alone as an unnecessary diff surface for a governance-only change. |
| **B — source comment/documentation** | `README.md`; `epoch/state.go`; `gcswitness/gcswitness.go`; `protocol/committed.go`; `conformance/faultproxy/faultproxy.go`; `conformance/witness/witness.go`; `conformance/spanneradapter/adapter.go` | "the frozen ADR-043 architecture"; "ADR-043 authority-epoch state machine" | Purely descriptive; carries no independent decision authority (GR-001 Rule 3). Not modified by this ADR (§10). Eligible for a future, separately-scoped, documentation-only update to cite ADR-044. |
| **C — test name/comment** | `rotationcommit/failure_injection_test.go`; `gcswitness/gcswitness_test.go`; `rotationcommit/emulator_shared_test.go`; `rotationcommit/epoch_integration_test.go` | comments describing "ADR-043's" commit-ambiguity matrix / protocol-state coverage | Same disposition as category B. Not modified. |
| **D — evidence historical provenance** | `docs/evidence/adr-043/real-gcp-safe-qualification/**`; `docs/evidence/adr-043/real-gcp-destructive-qualification/**` | directory path, README titles, evidence-manifest titles | **Not renamed or moved.** Historical provenance; see §18 for the documented meaning of the retained path. |
| **E — architecture reference** | This document; `EMG_ARCHITECTURE_DECISION_REGISTER.md` | — | This ADR is the new, correct architecture reference for this design. |
