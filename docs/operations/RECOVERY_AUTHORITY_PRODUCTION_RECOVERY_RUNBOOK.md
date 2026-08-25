# Recovery Authority production recovery runbook

**Document type:** L4 operations runbook

**Owner:** Recovery Authority operations owner

**Approval required before use:** Project Architect and Security owner

**Governing authority:** ADR-044 and ADR-045

**Status:** Implementation-preparatory; not production approval

`BLOCKER_A_STATUS = EXPERIMENTALLY_PASSED`

`ADR-044 = Accepted`

`ADR-045 = Accepted`

`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED`

## 1. Purpose and scope

This runbook operationalizes the Recovery Authority recovery constraints in ADR-044
and ADR-045. It does not authorize production deployment, bypass any protocol control,
or establish production approval. It does not apply to the separate Identity ADR-043
recovery mechanism.

Provider observations cited here come from the committed real-GCP safe and destructive
qualification evidence under
`services/recovery-authority/docs/evidence/adr-043/`. They establish the behavior
observed in those disposable-project trials, not an unlimited provider guarantee.

## 2. Roles and required separation

These are logical capabilities, not speculative IAM role names.

| Capability | Permitted responsibility | Required separation |
|---|---|---|
| Recovery Operator | Diagnose, collect evidence, and run the approved recovery state machine | Cannot sign, administer keys, alter billing/liens/retention, or administer projects |
| Spanner/Authority Administrator | Administer the transition-authority domain | Cannot administer signing or the witness |
| Witness/GCS Administrator | Administer the witness project within approved policy | Cannot sign, alter Spanner, or remove liens as an ordinary action |
| Signing Trust-Domain Administrator | Govern signing keys and signing policy | Administratively independent of the Spanner/GCS domain; cannot mutate either |
| Billing Relinker | Relink only an approved project/account pair after authorization | Not a runtime identity; cannot sign |
| Lien Modifier | Perform a separately authorized lien action | Not runtime or witness writer; break-glass only |
| Project Administrator | Restore the exact approved project | Cannot use project administration to cross other trust boundaries |
| Break-Glass Approvers | Jointly authorize an exact, time-bounded exceptional action | At least two independent approvers; never the acting operator alone |

No principal may combine capabilities in a way that defeats ADR-044 runtime separation
or ADR-045 signing administrative independence.

## 3. Incident classification

Classify and record one or more cases before acting:

- **A — witness read unavailable:** determine project, billing, IAM, and service state;
  do not infer loss.
- **B — project deleted/restored:** follow Section 5.
- **C — billing detached after restore:** follow Section 6.
- **D — Spanner Commit ambiguity:** follow Section 10; the result is not recoverable in
  the old epoch.
- **E — missing or invalid `COMMITTED` witness:** stop; never fabricate or reconstruct.
- **F — signing key unavailable:** use approved pinned historical public material for
  verification where applicable; recovery never gains signing capability.
- **G — signing key compromised:** apply Section 9 and the governed compromise ledger.
- **H — pinned historical public key unavailable:** stop and escalate.
- **I — compromise ledger unavailable:** fail closed and stop.
- **J — witness object conflict:** stop on unexpected key, generation, bytes, or digest.
- **K — `NEW_EPOCH_REQUIRED`:** apply Section 12; no old-epoch recovery action remains
  permitted.

## 4. Pre-recovery safety gate

Before any mutation, two authorized people independently verify and preserve:

1. exact environment and exact project/resource identifiers;
2. absence of staging/production cross-target confusion;
3. incident scope and current project lifecycle state;
4. `billingEnabled` and the expected, pre-approved billing relationship;
5. witness bucket identity, retention policy, and lock state;
6. exact object key, generation, provider hashes, and independently computed digest;
7. payload `signing_key_id` and caller-independent approved signing lineage;
8. pinned public-key fingerprint, integrity binding, and provenance;
9. compromise-ledger availability and applicable distrust state; and
10. available logs, responses, timestamps, and approvals.

Use fresh authoritative observations. Cached assumptions, list results, copied
identifiers, operator memory, and payload-supplied trust anchors do not satisfy this
gate. Any mismatch invokes Section 18.

## 5. Project restore sequence

Use this order exactly:

1. Restore the exact pre-approved project through the authorized project administrator.
2. Verify `lifecycleState = ACTIVE` against that exact project identity.
3. Verify the Cloud Billing association and `billingEnabled` state.
4. If billing is detached, stop witness access attempts and perform Section 6.
5. Verify `billingEnabled = true`.
6. Only then read and verify the witness object as specified in Section 7.

The destructive qualification trial observed that project restoration returned the
project to `ACTIVE` without restoring its billing association. This is an operational
availability dependency, not evidence of data loss. The same trial observed the exact
retained object, generation, bytes, retention, and lock after restoration and authorized
billing relink.

## 6. Billing relink

Billing relink is a distinct, authorized recovery action. The Billing Relinker must:

1. obtain approval for the exact expected project and pre-approved billing account;
2. independently compare both identities with the approved placement record;
3. relink only that pair;
4. make no billing-IAM, budget, account, or unrelated project change;
5. verify the expected association and `billingEnabled = true`; and
6. preserve the approval, actor, time, request, and redacted response in evidence.

The disposable qualification account is not production configuration and must never be
copied from qualification evidence into an operational command.

## 7. Witness verification

Correctness uses an exact-key read only; listing is never evidence that the required
record exists or is unique. In order:

1. read the caller-independently expected bucket and exact object key;
2. verify the key/path, object existence, expected generation, and retained bytes;
3. verify provider hashes and recompute the protocol digest from the bytes;
4. verify content binding against caller-independent environment, epoch, resource,
   operation, predecessor revision, and predecessor digest;
5. verify `signing_key_id` belongs to the caller-independent approved lineage;
6. verify pinned public-key integrity and capture provenance;
7. consult the independent compromise ledger and apply its trusted effective time;
8. verify the signature over the recomputed digest; and
9. only after every check succeeds, permit the recovery state machine to continue.

`CONTENT_BINDING != KEY_AUTHORIZATION != ACCEPTANCE_PROVENANCE`. Passing one check
never proves either of the others.

## 8. Signing and historical-key verification

- `signing_key_id` identifies the exact historical signing version.
- Authorization comes only from independently trusted approved-lineage configuration,
  never from the payload, witness, provider metadata, or operator input.
- Pinned public verification material is mandatory across disabled key versions and
  must retain its identifier binding, algorithm metadata, integrity, and provenance.
- `PinnedPublicKeyExists != KeyAuthorized`.
- Routine historical cryptographic verification does not require live KMS when valid
  pinned public material is available.
- The independent compromise ledger remains mandatory and unavailable ledger state
  fails closed.
- The recovery path has verification capability only; it never gains signing ability.

## 9. Compromise handling

`DISABLED != COMPROMISED`. Routine rotation or retirement does not invalidate a
record legitimately signed before rotation. Do not infer compromise from disablement,
scheduled destruction, or destruction alone.

For a governed compromise declaration, compare the record's trusted Spanner-derived
`commit_timestamp` with the ledger's trusted distrust-effective time. A record strictly
before the applicable time remains governed by the approved historical policy. A
record at or after that time, or a time whose trust cannot be established, does not
pass ordinary automated recovery and requires separate audited review. Never manually
backdate, forward-date, suppress, or rewrite compromise state. Ledger unavailability
means stop, not success.

## 10. Spanner Commit ambiguity

A later Spanner read **must never** resolve an ambiguous `Commit` outcome. Matching a
head row, history row, operation ID, digest, commit timestamp, audit log, change stream,
or administrator testimony cannot convert `AmbiguousCommitOutcome` into success.

The only permitted disposition is:

`UNRESOLVABLE_PREPARED_OPERATION` → terminate the old epoch → `NEW_EPOCH_REQUIRED`.

Do not issue a second transition intended to repair, complete, or overwrite the
ambiguous one.

## 11. GCS create ambiguity

GCS witness-create ambiguity is different from Spanner Commit ambiguity. An exact-key
read may determine whether the **already-authorized, already-signed exact bytes** were
persisted. It may not introduce alternate bytes or provenance.

No alternate key, overwrite, delete-and-retry, reconstruction, or newly signed
replacement is permitted. A mismatch or inconclusive exact-key result stops recovery.

## 12. `NEW_EPOCH_REQUIRED`

Assert `NEW_EPOCH_REQUIRED` after ambiguous Spanner Commit, loss of
`acceptedRotationContext`, an unresolvable prepared operation, or another ADR-044
condition that makes safe continuation impossible. Immediately set and enforce:

- `RecoveryAllowed = false`
- `RotationAllowed = false`
- `FenceReleaseAllowed = false`
- `PostgreSQLReconciliationAllowed = false`

Create no `COMMITTED` record after context loss. Terminate old-epoch activity and
escalate to the separately governed new-epoch/bootstrap path. This runbook does not
invent or authorize that future mechanism.

## 13. Explicitly forbidden actions

Never:

- fabricate `acceptedRotationContext`, `COMMITTED`, `PREPARED`, an epoch, operation ID,
  revision, or commit timestamp;
- manually update Spanner to match expected content;
- use a later Spanner read or any secondary evidence to resolve Commit ambiguity;
- overwrite a witness object, delete retained evidence, or create an alternate key/path;
- disable trust-anchor checks, accept an arbitrary `signing_key_id`, or bypass approved
  lineage;
- suppress, alter, or invent compromise state;
- sign from the recovery path;
- restore from unsigned, invalid, or incompletely verified `COMMITTED` data;
- use test/emulator keys in production; or
- use staging credentials or resources for production recovery.

## 14. Lien handling

The Bucket Lock project lien protects against project deletion. The qualification
trial observed that deletion was rejected while the lien existed and that authorized
lien removal did not disable object-level Bucket Lock enforcement. These are bounded
experimental observations.

Lien removal is a privileged governance action, never an ordinary recovery shortcut.
Do not remove it merely to simplify access or recovery. Any removal requires separate
break-glass authorization, a non-runtime Lien Modifier, exact scope, and complete audit
evidence.

## 15. Break-glass

Break-glass is permitted only when a documented incident cannot be handled with
ordinary least-privilege capabilities and delay would materially worsen the incident.
It requires two independent approvers, exact resource/action scope, a short expiration,
and an identified acting operator. Record approval before elevation, log every action,
revoke the temporary credential/session immediately afterward, verify ordinary access
is restored, and complete a post-incident security review. Break-glass never authorizes
a protocol bypass or prohibited action in Section 13.

## 16. Recovery evidence package

Retain a redacted, integrity-protected package containing:

- incident timeline, operator identities, approvals, and role separation;
- lifecycle and billing state before and after;
- witness bucket/object key, generation, metadata, retention, lock, and hashes;
- `signing_key_id`, approved lineage, pinned-key fingerprint and provenance;
- compromise-ledger decision and signature-verification result;
- epoch decision and final recovery disposition;
- commands or API requests and sanitized responses; and
- temporary access grants and proof of revocation.

Never retain tokens, private keys, credential files, signed URLs, unredacted identities,
or local workstation paths in the package.

## 17. Post-recovery checks

Before incident closure, independently verify project identity/state, billing state,
witness accessibility, exact object identity, retention and lock state, pinned-key
storage, compromise-ledger availability, Spanner authority state, epoch state, audit
delivery, and removal of every temporary elevation. Re-run the binding, authorization,
and signature checks. Record any unavailable check as a failed gate, not a warning.

## 18. Stop and escalation conditions

Stop all mutation and escalate to the Security owner and Project Architect for any:

- unexpected project/account, ambiguous identity, or environment mismatch;
- missing trust anchor, unapproved lineage, missing pinned key, or unavailable
  compromise ledger;
- signature failure, generation/hash/bytes mismatch, or evidence inconsistency;
- missing/unlocked retention, unexpected alternate object, or object conflict;
- Spanner Commit ambiguity or `NEW_EPOCH_REQUIRED` state;
- unauthorized billing or lien change; or
- action that would require a Section 13 prohibition.

Fail closed. Preserve evidence and do not improvise a recovery path.
