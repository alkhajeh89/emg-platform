# Recovery Authority — Production Recovery Runbook

**Status:** Draft operations runbook, standalone from architecture decision records.
**Derived from:** `EMG_ADR-044_RECOVERY_AUTHORITY_SPANNER_TRANSITION_AUTHORITY_AND_GCS_BUCKET_LOCKED_IMMUTABLE_WITNESS.md`
§13 ("This sequence and its prohibitions must be lifted into a standalone production
operations runbook before production deployment"), §14, and §17 item 6; and
`EMG_ADR-045_RECOVERY_AUTHORITY_SIGNING_ADMINISTRATIVE_INDEPENDENCE_AND_KEY_LIFECYCLE_PROTOCOL_EXTENSION.md`
§7, §7A, §7C, §7D; and the destructive-qualification evidence at
`services/recovery-authority/docs/evidence/adr-043/real-gcp-destructive-qualification/`.
**This document does not authorize, perform, or claim completion of production
deployment.** It exists so that when a real incident occurs against a real production
Recovery Authority deployment, the operator does not have to reconstruct correct
behavior from architecture prose under pressure. It records no new architecture
decision and changes no evidence, protocol constant, or code.

## 0. Preconditions before this runbook may be used against a real environment

This runbook assumes a production (or production-equivalent) Recovery Authority
deployment exists: a real Cloud Spanner authority database, a real GCS Bucket-Locked
witness bucket, a real, administratively independent signing trust domain (ADR-045
§4–§5), and a real, governed compromise/distrust ledger (ADR-045 §7) and pinned
historical public-key store (ADR-045 §7C).

**Status update (implementation-status wording only; no architecture or security
requirement below is changed by this update):** S3 (KMS signer + pinning + ledger), S4
(IAM), S5 (deployable binary), S6 (bootstrap), and S7 (real-Spanner process-loss/crash
qualification, ADR-044 §17 item 7) are now implemented and have each been qualified
against real Cloud infrastructure (see `services/recovery-authority/docs/evidence/adr-045/`
Tracks A–F and `services/recovery-authority/docs/evidence/adr-044/real-spanner-process-death-s7/`).
**This does not mean this runbook's precondition is satisfied.** Every one of those
qualifications used disposable, same-organization infrastructure. The specific property
this runbook's precondition actually requires — a real, **administratively independent**
signing trust domain (ADR-045 §4–§5, rejecting same-organization construction alone) —
remains unestablished, along with production realization of the compromise ledger and
pin store in their own genuinely independent administrative domains (ADR-045 §7, §7C)
and a completed production-approval decision (ADR-044 §22, ADR-045 §19). This runbook
remains not itself evidence that a production-ready deployment exists; it is written now,
in advance, so it is ready once that separate, explicit production-approval decision is
made.

## 1. Scope

Covers recovery of Recovery Authority state after an incident affecting the witness
project, the Spanner authority database, or both — including project deletion/restore,
billing disruption, and process loss during a transition. Does **not** cover Identity
ADR-043's separate refresh-token recovery procedure, general infrastructure incident
response, or key-lifecycle operations themselves (rotation, compromise declaration —
those are ADR-045 §6/§7 governance actions performed by the signing administrative
domain, not by this runbook's recovery operator).

## 2. Roles

Per ADR-044 §15, these are **distinct principals**; this runbook assumes that
separation is real, not aspirational, in whatever environment it is run against.

- **Recovery operator** — executes this runbook. Human or tightly-scoped, audited,
  ideally break-glass/just-in-time process. Holds read access to the Spanner authority
  database and the GCS witness bucket, and (only for the specific exceptional steps
  below) billing-relink and lien-inspection capability. **Never** holds signing
  capability (ADR-044 §15) and **never** holds compromise-ledger write capability
  (ADR-045 §7, property 2 — that authority is administratively independent of ordinary
  signing-domain administration, and by extension of this runbook's operator too).
- **Signing administrative domain** — administratively independent (ADR-045 §4–§5);
  this runbook never asks it to sign anything on the recovery operator's behalf outside
  its own normal, already-governed signing path. Recovery never signs (ADR-044 §7,
  ADR-045 §10 step 8's construction-order guarantee — `acceptedRotationContext` is not
  exported or constructible outside `rotationcommit`, and recovery code has no
  reachable path to it).
- **Compromise-ledger authority** — administratively independent of both of the above
  (ADR-045 §7, property 2). This runbook's operator consults the ledger; only this
  authority writes to it.
- **Approving authority for irreversible/exceptional actions** — a human distinct from
  the recovery operator, required before any step in §7 below.

## 3. Non-negotiable invariant

**Recovery never trusts `authority_head` content alone, and never trusts witness object
presence alone.** The only thing that ever authorizes treating a candidate transition as
accepted is a validly signed `COMMITTED` witness record that independently passes all of:
content binding, key authorization, and cryptographic signature verification (ADR-044
§7; ADR-045 §7A's three-check model, `CONTENT_BINDING != KEY_AUTHORIZATION !=
ACCEPTANCE_PROVENANCE`). Every step below exists in service of that invariant. If any
step in this runbook would require bypassing it, **stop and escalate — do not proceed**
(see §7).

## 4. Procedure — project and billing restoration (ADR-044 §13)

Follow in order. Do not skip ahead to witness reads before this section completes.

1. **Restore the project**, if deleted (`projects.undelete` or equivalent), and confirm
   the restore actually landed (do not assume success from the API response alone).
2. **Verify project `lifecycleState = ACTIVE`.** Do not proceed on a project still in
   `DELETE_REQUESTED` or any other non-`ACTIVE` state.
3. **Verify billing association.** Project restoration does **not** automatically
   restore Cloud Billing association (this is a confirmed empirical finding, ADR-044
   §13, not a hypothetical). Check `billingEnabled` before assuming GCS access will
   work.
4. **If billing is not associated, and only if this was the previously approved billing
   account for this project**, re-link it. Re-linking a *different* billing account
   than the one this project was previously and legitimately associated with is not a
   recovery action this runbook authorizes — that is a governance decision, not an
   incident-response reflex (see §9).
5. **Verify `billingEnabled = true`** after any relink, before proceeding.
6. **Verify expected bucket identity** — confirm the bucket name/project matches what
   this environment's `ExpectedBinding`-adjacent configuration expects, not merely "a
   bucket that looks right."
7. **Verify Bucket Lock/retention state** on the bucket is still what governance
   configured (retention policy present and locked). If it is not, stop — this is a
   governance-integrity anomaly, not a routine recovery step (see §7).

Only after all seven steps above succeed may the runbook proceed to §5.

## 5. Procedure — witness read and cryptographic verification

1. **Read the exact witness key** for the operation/environment/resource incarnation
   under recovery. Never construct, guess, or fall back to a different key. Never treat
   the *absence* of the expected object as license to proceed as if a `COMMITTED` had
   never been attempted — absence has its own handling in §6.
2. **Recompute the canonical digest independently** from the object's own bound fields
   (ADR-045 §7A step 3) — never trust a digest field read from storage, and there is no
   such field to trust in the first place; the digest is always recomputed, never
   persisted separately from the fields it covers.
3. **Verify content binding** against the caller-independent `ExpectedBinding`
   (environment, epoch, resource incarnation, operation, predecessor revision,
   predecessor digest) — ADR-044 §7, ADR-045 §7A step 1.
4. **Verify key authorization** — confirm the record's `signing_key_id` (V2 records
   only; see §8 below for V1) belongs to the independently configured approved signing
   lineage for this environment/resource (ADR-045 §7A step 2, §7D). This check is
   performed regardless of whether the signature would otherwise verify — a
   cryptographically valid signature from a key outside the approved lineage is still
   rejected. **This is the exact check that makes an attacker's own genuinely-owned,
   genuinely-valid signing key insufficient to forge acceptance** (ADR-045 §7A) — do
   not weaken, skip, or work around it as a "recovery expedient" under any
   circumstance.
5. **Resolve the exact historical public key** for the confirmed, now-authorized
   `signing_key_id`, from the pinned public-key store (ADR-045 §7C) — never from a live
   provider `GetPublicKey` call. Live KMS availability is not, and must not become, a
   dependency of this step (ADR-045 §7). If the pinned material for this `SigningKeyID`
   cannot be found, this is a **fail-closed condition** (§7), not a reason to fall back
   to a live lookup or to skip the check.
6. **Consult the compromise/distrust ledger** for this `signing_key_id` (and, per
   ADR-045 §7D, for its lineage). If a distrust-effective time is recorded and the
   record's own trusted `commit_timestamp` is at or after it, or the distrust-effective
   time cannot be established with confidence, this record requires separate, manual,
   audited review — it is **not** auto-accepted and **not** auto-rejected by this check
   alone (ADR-045 §7). If the ledger itself is unavailable at verification time, this is
   a fail-closed condition (ADR-045 §7, "fail-closed scope") — proceed to §7, do not
   proceed as though no compromise exists merely because the ledger could not be
   consulted.
7. **Cryptographically verify the signature** against the recomputed digest and the
   resolved, pinned public key.
8. Only if steps 3, 4, 6 (passed, not merely "not distrusted"), and 7 **all** pass does
   the record count as a validly authenticated `COMMITTED` acceptance. Any single
   failure — regardless of how the others resolved — means treat the transition as not
   accepted.

## 6. Epoch decision

Feed the outcome of §5 into the existing, frozen epoch state machine
(`internal/authority/epoch`) exactly as it already behaves — this runbook does not
redefine that logic, it only describes how a human operator drives it correctly:

- A record that passes every check in §5 step 8 → the transition is genuinely accepted;
  resumption may proceed under `ACTIVE(new_revision)` per the existing state machine
  (mirrors the emulator-proven T10 case).
- No record found, or a found record that fails any check in §5, in circumstances that
  the existing ambiguous-outcome handling classifies as ambiguous or otherwise
  unresolved → `NEW_EPOCH_REQUIRED`. Do not attempt to manually "resolve" this by any
  means other than the documented `NEW_EPOCH_REQUIRED` procedure. A new epoch is a
  correct, safe outcome — it is not a failure of this runbook, and treating it as one
  by improvising a shortcut around it is exactly the failure mode this runbook exists
  to prevent.

## 7. Forbidden actions — never a recovery technique, under any circumstance

Restated and unified from ADR-044 §13 and ADR-045's threat corrections, because a
human operator under incident pressure is exactly the failure mode these prohibitions
defend against:

- Fabricating, hand-constructing, or "temporarily" writing a `COMMITTED` record,
  epoch value, operation ID, or commit timestamp.
- Manually reconciling an ambiguous Spanner Commit outcome by directly inspecting or
  editing Spanner state to "decide" what must have happened — the existing, qualified
  ambiguous-commit handling is the only sanctioned resolution path.
- Bypassing, weakening, or reordering any step of the trust-anchor checks in §5 —
  content binding, key authorization, compromise-ledger consultation, or signature
  verification — for any reason, including "we're confident this is legitimate."
- Overwriting an existing witness object, creating a replacement bucket, or using a
  different object key than the exact expected one.
- Shortening or removing retention as a recovery technique.
- Treating witness object *presence* alone, or `authority_head` content alone, as
  acceptance provenance.
- Reconstructing, calling, or attempting to obtain `acceptedRotationContext` from
  recovery code — it has no exported type or constructor reachable outside
  `rotationcommit`, by design (ADR-045 §10; enforced today by
  `TestAcceptedContextHasNoExportedTypeOrConstructor`).
- Having recovery, or any recovery operator acting through it, sign anything. Recovery
  cannot sign and must never be given a path to.
- Re-linking a billing account other than the previously approved one without an
  explicit, separately recorded risk-acceptance decision (§9).
- Proceeding past a pinned-public-key-store or compromise-ledger unavailability by
  falling back to a live provider lookup or by assuming "not distrusted" in the
  ledger's absence.
- Using staging or production credentials outside the scope of the specific incident
  being handled.

If any forbidden action above appears to be the only way forward, the correct action is
to **stop and escalate to the approving authority (§2)**, not to proceed.

## 8. V1/V2 record handling

Production genesis is V2-exclusive going forward (ADR-045 §11); a V2 record's key
authorization check (§5 step 4) applies unconditionally. A pre-ADR-045 V1 record (no
`signing_key_id`, digested under the original `EMG-ADR043-COMMITTED-V1` domain
separator) has no key-authorization concept to check — its trust rests entirely on
content binding and signature verification against whatever single key that
environment used before key-identifier tracking existed. This runbook does not
introduce, and this codebase does not perform, any automatic V1/V2 format guessing;
each record's own recorded structure determines which verification path applies, never
caller inference (ADR-045 §11).

## 9. Break-glass / operator approval

Any step marked exceptional above (billing relink to a non-previously-approved
account, any deviation from §4–§6, any action not explicitly listed as routine) requires
sign-off from the approving authority (§2), recorded as an audit event (§10) *before*
the action is taken, not reconstructed afterward.

## 10. Audit evidence

Every recovery execution SHALL produce a retained record covering at minimum: which
steps in §4–§6 were performed and their outcomes; the exact witness key read; the full
outcome of each §5 sub-check (not merely a final pass/fail); the epoch decision reached
(§6); and, for any exceptional action under §9, the approval record. This mirrors the
evidence discipline already demonstrated in
`docs/evidence/adr-043/real-gcp-destructive-qualification/` — this runbook does not
lower that bar for real incidents.

## 11. Post-recovery verification

After resumption, independently re-verify (do not merely trust the recovery path's own
self-report):

1. The resumed epoch state permits exactly the actions the state machine says it
   should (`RecoveryAllowed`, `RotationAllowed`, `FenceReleaseAllowed`,
   `PostgreSQLReconciliationAllowed`, `NewEpochRequired` — cross-check all five, not
   just the ones relevant to the immediate next action).
2. A fresh, independent read of `authority_head` matches the revision number recorded
   in the verified `COMMITTED` payload.
3. No forbidden action from §7 was taken, confirmed against the audit record from §10.

## 12. Relationship to other documents

This runbook does not amend ADR-044, ADR-045, or Identity ADR-043. It does not claim
completion of any ADR-044 §17 production prerequisite. It exists to be ready the day
those prerequisites are complete, and should be reviewed and re-validated against the
concrete S3–S7 implementations once they exist, before being relied on operationally.
