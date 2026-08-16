# EMG ADR-045 — Recovery Authority: Signing Administrative Independence and Key-Lifecycle Protocol Extension

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-17
**Baseline:** `develop` at `4fc6c94b010f05b347b154066f3b9756e9e96f3a`
**Related:** ADR-044 (Recovery Authority: Spanner Transition Authority and GCS Bucket-Locked
Immutable Witness — the governing architecture this ADR extends; see §16), ADR-043
(Identity Durable Refresh State Database and Migration Authority — unrelated, unaffected;
see §16).

> **Acceptance note (2026-08-17).** Independent architecture/security review of this
> ADR found material trust-anchor, construction-order, and Cloud-KMS-lifecycle issues
> across two review passes: a missing verification trust anchor that would have allowed
> any actor holding any valid signing key to authenticate a forged record; a circular
> digest/signing construction order that would have made the specified protocol change
> non-implementable; and a factual error, found via live fact-checking against current
> official Cloud KMS documentation, about disabled-key public-key retrievability. All
> three were corrected in the document text itself — no architecture, protocol,
> cryptographic domain separator, or evidence artifact was changed to obtain this
> result. A final, focused independent review of the corrected text found zero
> remaining P0/P1/P2 findings (`ACCEPT_AS_CORRECTED`). This ADR is accepted on that
> basis.

> **This ADR authorizes architecture only.** It does not authorize production
> deployment and does not create or modify any GCP resource. See §19 (Production
> approval boundary) and §14 (S1 authorization boundary).

---

## 1. Context

ADR-044 (Accepted 2026-08-16) ratified the Spanner-sole-transition-authority /
GCS-Bucket-Lock-witness architecture but explicitly declined to select a realization of
its own §15A `SIGNING_ADMINISTRATIVE_INDEPENDENCE_REQUIREMENT`, and explicitly identified
(§17 item 10) that historical `COMMITTED` signature verification across key rotation is
unsupported by the current protocol — `protocol.CommittedPayload` carries no key
identifier, and `recovery.CommittedSignatureVerifier` assumes exactly one implicit
verification key. ADR-044 §17 items 9 and 10 record both gaps as production blockers and
reserve their resolution as "a separate, subsequent implementation-review decision."

This ADR is that decision. It was preceded by a bounded, read-only design phase (S0)
that surveyed the trust-domain options and produced an initial protocol-extension
proposal. This document independently re-verifies that proposal against source and
formally decides the questions ADR-044 reserved. Across its own drafting and two rounds
of independent adversarial review — including live fact-checking against current,
official Google Cloud documentation, not reliance on memory — four defects were found
and corrected before any code was written: S0's over-strict disabled-key rule (§7); a
missing verification trust anchor that would otherwise have reintroduced an
acceptance-provenance bypass (§7A); a circular digest/signing construction order that
would have made the resulting protocol change non-implementable (§10); and a factual
error about Cloud KMS's disabled-key public-key retrievability that would have left
§7's own correction unsupported without a mandatory pinning requirement (§7C). See §15
for the full consequences of each correction.

**Independent re-verification against source (baseline `4fc6c94b...`), performed before
drafting this ADR, confirmed every load-bearing S0 assumption:** no `signing_key_id` or
equivalent exists anywhere in `services/recovery-authority`; no key registry exists;
`CommittedSignatureVerifier.VerifyCommittedSignature` takes no key-identifier parameter;
`Signer.SignCommittedDigest` returns only a signature; `recovery.CommittedCheckpointVerifier`
has zero implementations, callers, or test references anywhere in the repository; no
deployable binary, production KMS integration, or any production Recovery Authority
state exists. None of these were assumed — each was independently re-checked by direct
source inspection immediately before this document was written.

## 2. Problem

Two problems, both already identified and scoped by ADR-044, require a concrete decision
before any implementation:

1. **No signing trust domain has been selected.** ADR-044 §14 row G leaves the
   organization-administrator threat explicitly open until a concrete, independently
   administered signing trust domain is chosen and qualified (§15A).
2. **The protocol cannot support historical signature verification across key
   rotation.** A `CommittedPayload` carries no record of which key signed it, so a
   future key rotation would make every prior record unverifiable under a
   "current-key-only" design — a gap ADR-044 §17 item 10 explicitly prohibits shipping.

## 3. Decision

1. **Trust-domain selection:** `SIGNING_TRUST_DOMAIN_DECISION = OPTION_A` — an
   independently administered GCP-native signing trust domain, realized as a project
   deliberately kept outside the IAM hierarchy and administrative reach of the EMG
   Spanner/GCS administrative domain (§4).
2. **Protocol extension:** `CommittedPayload` gains a `signing_key_id` field,
   cryptographically bound into `CanonicalDigest`, under a new, additive V2 domain
   separator (§7–§9).
3. **Key-governance semantics:** historical verification depends on cryptographic
   validity plus a *governed compromise record* — not on a key's current
   enabled/disabled administrative state, which is not, by itself, evidence of
   anything about historical legitimacy (§10, correcting an S0 defect).
4. **`CommittedCheckpointVerifier` is removed** as dead, never-implemented,
   never-called surface (§12).
5. **Verification trust anchoring:** cryptographic binding of `signing_key_id` into
   the digest (item 2) and authorization to represent the Recovery Authority are two
   separate properties, and the first never establishes the second. **`CONTENT_BINDING
   != KEY_AUTHORIZATION != ACCEPTANCE_PROVENANCE`** — three independent, all-mandatory
   checks, none of which may substitute for another (§7, correcting a second S0/initial-draft
   defect found during this ADR's own review).
6. **Mandatory public-key pinning:** because Cloud KMS's live public-key retrieval
   stops at disablement, not destruction (independently re-verified against current
   official documentation), preserving historical verifiability across routine key
   rotation SHALL be treated as a required architectural property — every approved
   signing key's public verification material SHALL be durably pinned while the
   version is still `ENABLED` — never as an optional S3 hardening recommendation (§6,
   §7C, correcting a third defect found during this ADR's own review). `PinnedPublicKeyExists`
   never implies `KeyAuthorized`; content binding, key authorization, compromise
   status, and acceptance provenance all remain independently mandatory regardless of
   how the public key material was obtained.

## 4. Selected trust-domain architecture

**Governing property, stated precisely (not a claim about any specific GCP resource
shape):** the administrative authority that controls the EMG Spanner/GCS domain SHALL
NOT be able to grant itself signing permission, modify signing-key IAM, replace signer
workloads, impersonate the signing runtime, rotate/revoke/destroy keys, or change the
administrative policy governing the signer. Conversely, signing-domain administrators
SHALL NOT be able to mutate Spanner authority state, mutate GCS witness state,
administer witness retention, remove witness-project liens, modify authority-project
billing, or become Recovery Authority runtime operators through any inherited
privilege. **Runtime separation (ADR-044 §15) is necessary but not sufficient by
itself; this is an independent, additional administrative-trust-domain property
(ADR-044 §15A), and this ADR's obligation is to define it precisely, not to weaken it
for implementation convenience.**

**Minimal selected realization:** an independently administered GCP-native project
(the "signing project") with no IAM-inheritance relationship — no shared organization,
no shared folder, no shared parent resource — to the project(s) administering Spanner
and the GCS witness (the "authority/witness domain"), administered by a distinct,
non-overlapping set of human approvers/credentials.

**This ADR does not assert, as an established fact, that any particular GCP
resource-parent shape (org-less project, separate organization, separate folder with
IAM Deny policy, etc.) is automatically secure.** The governing property is
administrative independence — who can actually reach whose IAM policy — not a
particular resource topology. GCP's exact IAM-inheritance semantics for whichever
concrete resource shape is chosen (and any edge case, such as billing-account-level or
Cloud-Identity-domain-level reach that could cross an otherwise-independent boundary)
**must be independently verified against current, authoritative GCP documentation and
proven during implementation/provisioning qualification** (ADR-044 §17 item 9) — it is
not established by this ADR as a repository-verifiable fact, because it cannot be:
this repository contains no evidence of EMG's current GCP organization topology, and
this ADR does not access GCP to determine it.

**Rejected: same-organization construction alone (ADR-044 §15A "Option C").**
Independently reconfirmed: a genuine Cloud Identity organization-level administrator
retains the ability to modify org policies and IAM-Deny constraints that any
same-organization folder/project separation depends on, so a same-org construction
cannot fully close the row-G threat as modeled (compromise of "the organization
administrator"). This is not merely inconvenient to implement; it does not satisfy the
stated requirement, so it is rejected on security grounds, not selected against for
speed.

**Rejected (as a default; not excluded as a future alternative): external HSM/signing
service outside GCP entirely ("Option B").** Provides no security property beyond a
genuinely independent GCP-native trust domain, while adding a new vendor relationship,
a new integration surface, and a new bespoke DR/monitoring posture. Not selected
because it introduces delivery/operational cost without a required property Option A
lacks — not because it is insecure. A future, separately reviewed decision may revisit
this if a concrete requirement Option A cannot meet is identified.

## 5. Signing authority model

- **Asymmetric signing only.** Private key material is never exported from its
  provider boundary and never returned to any caller.
- **Exactly one narrowly scoped signer runtime identity** may invoke signing, granted
  only the specific sign-capability on the specific key — no broader key-administration
  right.
- **Public verification is independent of signing permission.** Any party holding or
  able to fetch the relevant public key may verify; verification capability is
  deliberately unprivileged.
- **Signing-domain administrators control the full key lifecycle** (creation,
  rotation, disablement, destruction, break-glass) within the signing project; **EMG
  authority/witness administrators have no such control and no IAM path to acquire
  it.**
- **Signing-domain administrators have no IAM path into the Spanner/GCS domain** —
  symmetric to the above.
- **Break-glass** (any path capable of granting new signing capability) requires
  approval independent of, and in addition to, ordinary Spanner/GCS administrative
  authority, and is auditable.
- **Audit evidence** for every key-administration and signing operation is retained
  for at least the environment's required recovery/audit retention window.

This ADR does not hard-code specific GCP IAM role names beyond what is already
independently verifiable (no such verification was performed for this document, since
it does not access GCP); exact role bindings remain an implementation task, reviewed
against the properties above, not a decision this ADR makes.

## 6. Key lifecycle

Governed at minimum: creation, activation, signing, key identification, verification,
rotation, historical verification, disablement, compromise response, revocation,
unavailable-key handling, retirement, destruction, break-glass, audit, and
requalification after any key-policy or signer-implementation change.

**Selected key identifier: provider-native immutable key-version identity.** For the
GCP-native realization selected in §4, this is Cloud KMS's own fully-qualified
`CryptoKeyVersion` resource name — already immutable, already provider-guaranteed
unique, already safely serializable as an opaque string. No custom key registry is
invented.

**The protocol type itself remains provider-agnostic:** `SigningKeyID` is a validated,
opaque, non-empty, bounded-length string — the same pattern already used by
`protocol.EnvironmentID`/`OperationID`. Cloud-KMS-specific resource-name parsing
semantics are never encoded into the core `protocol` package; a future non-GCP
realization (external HSM, or a different provider) remains representable without a
further protocol change, only a different concrete `Signer`/verifier implementation.

**Which key version is active for new signing is caller-side configuration, not a
provider-selected default.** Cloud KMS's automatic "primary version" concept applies
to symmetric encryption keys (`CryptoKey.primary` driving `Encrypt`); it does not apply
the same way to asymmetric signing. `AsymmetricSign` targets an exact
`CryptoKeyVersion` resource named explicitly in the request — Cloud KMS never
auto-selects an active signing version on the caller's behalf. The production Signer
implementation (S3+) therefore MUST itself track, as explicit configuration, which
specific `CryptoKeyVersion` is currently active for new signatures, and MUST determine
that identifier *before* signing (§10) — never infer it from a provider-side default
that does not exist for this operation type.

**Critical invariant:** a key version SHALL NOT be destroyed while any retained,
auditable `COMMITTED` record signed under that version remains within its required
verification/evidence-retention horizon.

**Correction (found and independently re-confirmed against current, official Google
Cloud documentation during this ADR's own review — before any code was written):** an
earlier draft of this section stated that a disabled version's public key "remains
retrievable... until destruction." **This is factually incorrect for Cloud KMS and is
corrected here.** Official Cloud KMS documentation states plainly: *"You can retrieve a
key version's public key only if the key version is enabled"* — live retrieval via
`GetPublicKey` stops at **disablement**, not destruction. The exact provider lifecycle,
confirmed against current documentation:

- **ENABLED** — the only state in which `AsymmetricSign` may be invoked and in which
  `GetPublicKey` may be called to retrieve the public key live.
- **DISABLED** — new signing is refused; live `GetPublicKey` retrieval is also refused,
  not merely signing. A disabled version can be re-enabled.
- **Scheduled for destruction** (the provider's pre-destruction warning window) — no
  cryptographic operation of any kind succeeds against a version in this state; it is
  a distinct, irreversible-lifecycle warning state requiring an explicit governance
  check before proceeding, and (where the provider supports it) an explicit
  cancellation path back to `DISABLED` if destruction was scheduled in error.
- **DESTROYED** — the provider-held key version is no longer a usable source of
  recovery material at all; its public key is no longer available for download from
  the provider by any means. This state is genuinely irreversible.

**This means the load-bearing invariant is not "destruction is the only thing that
matters" — it is disablement.** Preserving historical verifiability across routine
rotation is therefore not a property Cloud KMS provides passively; it requires an
explicit, mandatory architectural step, specified in §7C.

## 7. Compromised/disabled key semantics (correcting an S0 defect)

**S0 stated, incorrectly, that any disabled historical key must always cause
verification failure.** Independent adversarial review for this ADR found this too
strict and corrects it here, before any code is written.

**The governing distinction is cryptographic validity versus key-governance status,
and — critically — key-governance status is not a single flag but requires
distinguishing *why* a key is no longer active for new signing:**

- **Routine rotation/retirement.** A key version disabled only because a newer version
  became the active signing key remains fully valid for verifying every record it
  legitimately signed — **not because its public key remains live-retrievable after
  disablement (§6's correction establishes that it does not), but because its public
  verification material was independently, durably preserved while the version was
  still `ENABLED`, per the mandatory requirement in §7C.** Cryptographic *enablement*
  governs the ability to produce *new* signatures; it never governs the validity of
  signatures already produced, and current provider-reported enabled/disabled state is
  never itself the source of historical trust — the pinned material and the approved
  lineage (§7A) are. Treating routine disablement as invalidating history remains
  wrong, exactly as originally stated; what changes in this correction is *why* it
  remains verifiable — provider retrievability was never the mechanism, and never
  should have been assumed to be.
- **Compromise revocation.** A key version believed compromised requires a distinct,
  explicitly governed **compromise record** — an audited fact, independent of the
  key's live provider-reported enabled/disabled state, stating the key-id and a
  **distrust-effective time**. A `COMMITTED` record verifies as trustworthy only if,
  in addition to passing cryptographic verification: (a) its signing key version's
  public key is still retrievable (not destroyed), and (b) its own `commit_timestamp`
  — already an existing, protocol-bound field, itself derived from Spanner's
  TrueTime-assigned, structurally-validated commit timestamp per ADR-044 §5 — is
  strictly earlier than any applicable distrust-effective time recorded for that
  key-id, or no compromise has been declared for that key-id at all. A record whose
  `commit_timestamp` is at or after a declared distrust-effective time, or for which
  the distrust-effective time cannot be established with confidence, is **not**
  auto-accepted or auto-rejected by this check alone — it SHALL be treated as
  requiring separate, manual, audited review, never as passing ordinary automated
  verification.
- **Fail-closed scope, precisely stated.** Unavailability of the *compromise record*
  specifically (the governed distrust ledger) at verification time SHALL fail closed
  — an inability to rule out an undetected compromise is itself a verification
  failure. Live Cloud KMS availability is **not** a dependency of ordinary historical
  verification at all once §7C's mandatory pinning requirement is satisfied — routine
  historical verification uses the pinned public verification material, never a live
  `GetPublicKey` call, so provider availability (or a version's live enabled/disabled
  state) is simply not in the ordinary verification path to begin with.

This compromise record is a governance artifact distinct from live Cloud KMS state — a
pattern already precedented in this repository's own conventions (Identity ADR-043
Amendment 1's immutable, independently-queryable version history used for
rollback/replay detection is an analogous, though not identical, mechanism: a trusted
record consulted independently of ordinary live state). It is **not** the "custom key
registry" §8 rejects — that rejection concerns inventing an identifier-to-public-key
mapping (unnecessary, since Cloud KMS's own resource names already serve that role);
the compromise ledger answers a different question entirely (whether a previously
*authorized* key is now distrusted, and from what effective time), never how to resolve
an identifier to a public key. **Building the actual compromise-record mechanism is out
of this ADR's and S1's scope** (it belongs to the production Signer/KMS adapter work,
S3+); this ADR's obligation is to define the required semantics precisely enough that
S1's interface shape (§10) can accommodate it without a later breaking change.

**Required governance properties of the compromise ledger (binding on the S3+
mechanism, not designed here).** A compromised or malicious signing-domain
administrator must not be able to erase, suppress, or backdate their own distrust
declaration — the ledger would otherwise defeat itself circularly. The compromise
ledger, whatever its concrete S3+ realization, SHALL be:

1. **append-only or equivalently immutable** — no prior entry may be edited or
   retroactively altered, mirroring the same non-reuse/immutability discipline already
   required of the Approved Recovery Authority concept in Identity ADR-043 Amendment 1
   (an analogous, not identical, mechanism);
2. **administratively independent of ordinary signing-domain administration** — the
   principals who can write a compromise declaration SHALL be distinct from, and SHALL
   NOT be reachable by, the ordinary signing-key administrators of §5; at minimum, this
   authority sits at the same governance tier as the break-glass approval path (§5),
   never below it;
3. **auditable** — every write to the ledger is itself an audited event;
4. **protected against unilateral deletion, suppression, or backdating** by any single
   administrator, including a signing-domain administrator;
5. **available to verification without granting signing capability** — reading the
   ledger to check a key's distrust status must never require, or be bundled with, any
   permission that could also be used to sign.

### 7A. Verification trust anchor (correcting a second defect found during this ADR's own review)

**A first draft of this ADR treated `signing_key_id`'s cryptographic binding into the
digest (§8) as sufficient on its own to trust the record. It is not, and stating
otherwise would silently reintroduce exactly the vulnerability class ADR-044 §7's
`CONTENT_BINDING != ACCEPTANCE_PROVENANCE` principle exists to close.**

Binding a value into a signed digest proves only that the value was not *tampered with*
after the fact — it proves nothing about whether the value was ever *legitimate* in the
first place. Concretely: nothing in a cryptographic-binding-only design stops an
attacker who possesses *any* valid asymmetric signing key anywhere — including one
they generated themselves, in a Cloud KMS project they fully control, with no
relationship to EMG's signing trust domain at all — from constructing a complete,
internally self-consistent `CommittedPayload`: arbitrary content-binding fields of
their choosing, `signing_key_id` set to their own key's resource name, `CanonicalDigest`
correctly recomputed over that exact content (which, per §8, already includes their
chosen `signing_key_id`), and a signature that genuinely, correctly verifies — because
they hold the private key for the very identifier they named. Every check specified
elsewhere in this ADR would pass. This is a full acceptance-provenance bypass,
equivalent in effect to forging a `COMMITTED` record outright.

**Correction — a third, independent, mandatory check is required: key authorization.**
`CONTENT_BINDING != KEY_AUTHORIZATION != ACCEPTANCE_PROVENANCE`. Three separate
properties, three separate checks, none substituting for another:

- **Content binding** (already required, ADR-044 §7) — do the payload's bound fields
  match what the caller independently expected?
- **Key authorization** (new in this correction) — does the payload's `signing_key_id`
  belong to the specific, independently approved signing lineage for this
  environment/resource — never derived from the payload itself, from GCS, from the
  claimed `signing_key_id`, or from any attacker-controlled provider metadata, but
  supplied to the verifier out-of-band by the caller, exactly as `ExpectedBinding`'s
  other fields already are?
- **Acceptance provenance** (already required, ADR-044 §7) — does a valid signature
  exist over the independently recomputed digest?

`ExpectedBinding` (`recovery/committed_verification.go`) SHALL gain a new field
carrying the caller-independently-known approved signing lineage (e.g., the specific
`CryptoKey` — not merely `CryptoKeyVersion` — resource prefix under which every
legitimate `signing_key_id` for this environment/resource must fall, for the GCP-native
realization selected in §4). `VerifyPersistedCommitted` SHALL reject any payload whose
`signing_key_id` does not belong to that approved lineage, as an independent check —
performed regardless of whether content binding and cryptographic verification would
otherwise both pass.

**Mandatory verification sequence**, all steps independent and all mandatory (a failure
at any step is a full verification failure, regardless of any later step's outcome):

1. Verify persisted content binding against the caller-independent `ExpectedBinding`
   (unchanged from ADR-044 §7 — environment, epoch, resource incarnation, operation,
   predecessor revision, predecessor digest).
2. Verify `signing_key_id` belongs to the independently approved signing lineage
   (new — this subsection).
3. Recompute the V2 `CanonicalDigest` over the payload's own bound fields, including
   `signing_key_id` — never trust a self-reported digest.
4. Resolve the exact historical public key for the confirmed, now-authorized
   `signing_key_id`.
5. Apply the compromise/distrust semantics above (routine-rotation vs.
   compromise-revocation, per the ledger).
6. Cryptographically verify the signature against the recomputed digest and the
   resolved public key.

No step may be skipped, reordered around, or treated as redundant with another; in
particular, step 6 passing never substitutes for step 2, and step 2 passing never
substitutes for step 6.

### 7B. IAM scoping for the future signing runtime (S3 guidance, not provisioned here)

The eventual S3 signer runtime identity SHALL be scoped to the narrowest practical
signing permission the selected provider supports — for the GCP-native realization
selected in §4, this means invoke rights limited to the specific active
`CryptoKeyVersion` where the provider's IAM model permits version-level granularity,
rather than a blanket grant across the whole `CryptoKey`. It SHALL NOT receive key
administration, rotation/disablement/destruction administration, Spanner mutation
rights, GCS witness administration rights, or project administration rights of any
kind — all already prohibited by §5's runtime-separation model; this subsection adds
only the version-level granularity refinement. This narrows, as defense in depth, the
blast radius of Attack 18's legitimate-signer-misuse variant (§13): a signing principal
authorized only for the currently active version cannot use a different, also-valid
historical version even if it is administratively present in the same `CryptoKey`. No
IAM binding, project, or role is created by this ADR.

### 7C. Mandatory public-key pinning (closing the final defect found during this ADR's own review)

**§6 established that Cloud KMS's live `GetPublicKey` stops working at disablement, not
destruction.** Preserving historical `COMMITTED` verifiability across routine key
rotation is therefore not a passive provider property — it is a **mandatory
architectural requirement**, not an optional S3 hardening recommendation as an earlier
draft of this ADR characterized it.

**Required rotation order** (S3+ scope; specified here so S3 does not have to
rediscover it):

a. create/approve the new signing `CryptoKeyVersion`;
b. retrieve its public verification material *while it is `ENABLED`* and independently,
   durably preserve ("pin") that material;
c. qualify verification against the pinned material (prove a signature produced by
   that exact version verifies correctly against the pinned copy);
d. switch the caller-controlled active-signing configuration (§6) to the new version;
e. stop using the retiring version for new signing;
f. **confirm** the retiring version's own historical public key was durably pinned
   *before* proceeding to the next step — this confirmation is itself a required,
   auditable gate, not an assumption;
g. only after that confirmation may the retiring version be disabled.

**A version disabled before its public key was pinned is an operational governance
violation**, not a scenario this architecture treats as recoverable after the fact — a
disabled, unpinned version's historical records become permanently unverifiable
through no fault of the protocol (Attack 2, §11).

**What must be preserved for every approved signing version, at minimum:**

- the immutable `SigningKeyID`;
- the public verification material itself;
- the cryptographic algorithm/key-metadata required to correctly interpret that public
  key;
- an integrity binding between the `SigningKeyID` and the pinned public key (so the
  pinned copy cannot be silently swapped for a different key under the same
  identifier — Attack 3, §11);
- provenance evidence that the pinned material was captured from the independently
  approved signing lineage (§7A), not from an arbitrary or attacker-supplied source.

**This pins public material only — never private key material.** Private signing key
material never leaves the provider boundary (§5); pinning applies exclusively to
already-public verification material, which is not secret and was never intended to be.

**Critical invariant, restated precisely: `PinnedPublicKeyExists` does NOT imply
`KeyAuthorized`.** A pinned public key is verification material only — it answers "what
cryptographic public material corresponds to this already-authorized historical
version," nothing more. It never substitutes for, and is checked entirely separately
from:

- **content binding** (do the payload's fields match what was independently expected?);
- **key authorization** (§7A — does `signing_key_id` belong to the approved lineage?);
- **compromise/distrust status** (§7 — has this specific key been declared distrusted
  as of the record's trusted `commit_timestamp`?);
- **acceptance provenance** (does the signature cryptographically verify?).

All four checks remain independently mandatory regardless of whether the public key
used to perform the fourth check came from a live provider call or pinned storage — the
*source* of the public key material changes nothing about which checks must pass.

**Distinguishing the three governance responsibilities this ADR now defines, so they
are never merged into one implicit lookup table:**

| Responsibility | Question it answers | Governed by |
|---|---|---|
| Approved signing lineage (§7A) | Is this signing authority authorized at all? | Caller-independent `ExpectedBinding` configuration |
| Pinned public key (this subsection) | What cryptographic public material corresponds to this already-authorized historical version? | Durable, integrity-protected, provenance-evidenced storage, indexed by `SigningKeyID` |
| Compromise ledger (§7) | Is this previously-authorized key distrusted, and from what trusted effective time? | The independently governed distrust ledger |

**Minimum governance properties required of the pinned-key storage mechanism** (S3+
scope; no concrete product selected here): integrity-protected; auditable; durable for
the complete evidence-retention horizon; indexed by immutable `SigningKeyID`; unable to
silently replace the pinned public key for an existing `SigningKeyID` once recorded;
independently verifiable. This is **not** a new custom key-*identifier* registry (§8
still rejects that) — Cloud KMS resource names remain the identifier scheme; this is
storage for the public *material* an already-legitimate identifier resolves to,
distinct in responsibility from both §7A's lineage check and §7's compromise ledger, per
the table above.

### 7D. Approved-lineage lifecycle (resolving the one prior P2 finding)

An approved signing lineage (§7A) can itself have lifecycle state, distinct from any
individual key version's compromise state:

- **Approved** — the current, caller-configured `ExpectedBinding` lineage value;
  ordinary new signing and verification both proceed against it.
- **Superseded** — a formerly approved lineage that has been deliberately replaced
  (e.g., migrating to a new `CryptoKey` for governance reasons unrelated to
  compromise), but was never itself distrusted. Historical `COMMITTED` records created
  while a superseded lineage was the approved one remain governed by
  authorization-at-the-time semantics: they were legitimately authorized when created,
  and superseding the lineage for *future* signing does not retroactively revoke them.
  New signing under a superseded lineage is forbidden.
- **Distrusted** — a lineage-level compromise declaration, governed by the same §7
  compromise-ledger properties and distrust-effective-time comparison already defined
  for individual keys, applied at the lineage level.

This is governance metadata about the caller-supplied trust anchor, not a new
`CommittedPayload` field — no protocol change is implied. For current single-lineage
production genesis, no lineage-replacement mechanism is required yet; if and when
lineage replacement becomes necessary, it requires its own separately governed update
to the independently supplied `ExpectedBinding` trust anchor, reviewed with the same
rigor as the original lineage approval — not invented ad hoc at that time.

## 8. Key-identifier protocol extension

`CommittedPayload` V2 gains exactly one new field: `signing_key_id`.

Requirements:

- non-empty;
- bounded length;
- canonically encoded exactly like the existing string fields (deterministic CBOR, no
  special-casing);
- **cryptographically bound** — included as an entry in `CanonicalDigest`'s input map,
  so any tampering changes the recomputed digest and causes verification to fail;
- immutable once the payload is constructed;
- supplied only by the actual signing operation that produced the accompanying
  signature — never independently invented, inferred, or supplied by a caller
  disconnected from that operation (§10).

**Explicitly rejected:** an unsigned/out-of-band key identifier (decouples key
attestation from the exact content it authenticates); a verifier that tries all
historical keys (creates ambiguous historical verification and an unbounded
trial-and-error operation, contrary to this protocol's single-linearization-point
discipline); inferring key identity from any existing, unrelated field (a hidden,
non-obvious lookup rule); and any hidden provider-specific lookup rule not expressed in
the protocol's own bound fields.

## 9. Selected V2 domain separator

`SELECTED_V2_DOMAIN_SEPARATOR = EMG-ADR044-COMMITTED-V2`

**Rationale, independently reasoned rather than mechanically inherited from S0:** the
question is whether a version-incrementing domain separator should reference the ADR
that governs the overall protocol *family* (ADR-044) or the ADR that happens to
introduce a particular version increment (this document, ADR-045). The existing V1
separators already establish the convention that the prefix identifies the governing
architecture, not the specific commit or document that authored a given field —
`DomainSeparator`'s own doc comment calls it "one canonical ADR-043 record family." If
every future version increment stamped a new domain separator with whichever ADR
number happened to introduce it (`EMG-ADR045-COMMITTED-V2`, a hypothetical
`EMG-ADR046-COMMITTED-V3`, and so on), the domain-separator namespace would fragment
across an ever-growing set of unrelated ADR numbers with no stable anchor, making it
*harder* for a future reader to recognize that these are all the same protocol family
at different versions. Keeping a stable `EMG-ADR044-*` prefix across every version,
with the trailing `-V{n}` suffix carrying the version signal, mirrors ordinary software
package-versioning convention (a stable package name, an incrementing version) and is
the clearer long-term provenance rule. `EMG-ADR044-COMMITTED-V2` is therefore selected
on independent architectural grounds, not by default.

This is a **new, additive** constant. It does not replace, rename, or alter
`DomainCommitted = "EMG-ADR043-COMMITTED-V1"` or any of the other six existing
`EMG-ADR043-*` constants, all of which remain byte-for-byte immutable. **Not created in
this document** — this ADR authorizes S1 to create it in code (§14).

## 10. Interface evolution and construction order

**A first draft of this ADR specified an impossible construction order and is
corrected here.** §8 requires `signing_key_id` be included in `CanonicalDigest`, which
must be computed *before* signing. The first draft's `Signer` interface, however, had
the signer *return* `keyID` only as a result of the signing call — meaning the digest
would need to include a value that is not yet known at the time the digest is
computed. As drafted, `CommittedPayload` construction could not be correctly
implemented at all. This also conflicts with how every other bound field is already
handled: `environmentID`, `authorityEpoch`, and the rest are all known from
`acceptedRotationContext` *before* `CanonicalDigest` is computed — `signing_key_id` was
incorrectly treated as an exception. It is not: per §6's correction, the caller already
knows its intended active `CryptoKeyVersion` before invoking `AsymmetricSign` (Cloud
KMS requires the caller to name the target version explicitly), so this information is
available up front, not discovered afterward.

**Corrected `Signer` interface — a pre-sign selection method is added:**

```go
// rotationcommit.Signer — a pre-sign selection method, and a confirming
// (not originating) key identifier on the sign result.
type Signer interface {
    // ActiveKeyID reports the SigningKeyID this Signer currently intends to
    // use for the next signature, queried before the digest that will be
    // signed is constructed. It performs no signing.
    ActiveKeyID(ctx context.Context) (protocol.SigningKeyID, error)

    // SignCommittedDigest signs a digest that already includes the
    // SigningKeyID returned by the immediately preceding ActiveKeyID call.
    // The returned keyID is a defense-in-depth confirmation of the exact
    // key version actually used -- it is checked against, never treated as
    // the source of, the identifier already bound into digest.
    SignCommittedDigest(ctx context.Context, digest protocol.Digest32) (
        signature []byte, keyID protocol.SigningKeyID, err error,
    )
}

// recovery.CommittedSignatureVerifier -- two added parameters, unchanged from
// the first draft's proposal.
type CommittedSignatureVerifier interface {
    VerifyCommittedSignature(
        ctx context.Context,
        keyID protocol.SigningKeyID,
        signedAt time.Time,
        digest protocol.Digest32,
        signature []byte,
    ) error
}
```

`signedAt` is sourced from the payload's own already-trusted `CommitTimestamp()`, so a
concrete verifier implementation can apply §7's distrust-effective-time comparison
without a further interface change later.

**Corrected construction sequence** (replacing the first draft's sequence in full):

1. `acceptedRotationContext` exists, as the direct, same-operation result of a
   `Commit` classified `UnambiguousSuccess` (unchanged, ADR-044 §7/§9) — the sole
   provenance gate for `COMMITTED` construction; nothing in this ADR weakens or bypasses
   it.
2. Call `signer.ActiveKeyID(ctx)` to obtain the intended `signing_key_id` — *before*
   any digest is constructed.
3. Construct the unsigned V2 `CommittedPayload`, including that `signing_key_id`
   value, from `acceptedRotationContext`'s fields.
4. Compute `CanonicalDigest` over the complete V2 field set, including
   `signing_key_id` — the digest now genuinely contains the value it is required to
   bind.
5. Call `signer.SignCommittedDigest(ctx, digest)`.
6. The signer's returned `keyID` is a **mandatory confirmation check**, never new
   information: it SHALL equal the `signing_key_id` already bound into `digest` at
   step 3–4.
7. **If the returned/confirmed key ID does not equal the key ID already bound into the
   digest, this is a hard construction failure** — `buildCommittedPayload` SHALL
   return an error and produce no payload. It SHALL NOT silently recompute a new
   digest with the differing key ID, SHALL NOT silently re-sign, and SHALL NOT proceed
   with either the original or the differing identifier (Attack 16, §13).
8. Only after step 6 confirms a match does `buildCommittedPayload` attach the
   signature via `WithSignature`.

**Formal requirements, regardless of exact Go syntax:**

1. The intended key identifier is determined *before* the digest it will be bound into
   is computed — never discovered only after signing.
2. The signer's post-signing return value is a confirmation of the identifier already
   bound into the digest, not its origin.
3. No caller may supply a key identifier independently of `ActiveKeyID`/the confirming
   `SignCommittedDigest` result — `buildCommittedPayload` (the sole call site) SHALL
   thread these values directly, never accept or construct a key identifier
   separately.
4. A mismatch between the pre-bound and post-signing-confirmed key identifier is a
   hard construction failure (step 7 above) — never silently resolved by re-signing,
   re-binding, or preferring either value.
5. `buildCommittedPayload` SHALL reject an empty or unset key identifier at any point
   in this sequence exactly as it already rejects an empty signature today.
6. The verifier receives the persisted, signed key identifier and signing time exactly
   as recorded in the payload — never a value independently supplied by the caller
   outside the payload's own bound fields (§7A step 1 vs. step 2: this is distinct from,
   and in addition to, the key-authorization/lineage check).
7. The verifier fails closed for an unknown, unresolvable, or unauthorized (§7A) key
   identifier.

A struct wrapper (e.g., bundling `Signature`/`KeyID`, or the verifier's four
parameters) was considered and rejected as unnecessary: each parameter already has a
distinct Go type (`[]byte` vs. `SigningKeyID` vs. `time.Time` vs. `Digest32`), so
positional-argument confusion is already prevented by the type system without added
indirection. This ADR governs the semantics above; exact parameter ordering or minor
syntactic packaging remains an S1 implementation detail, provided every formal
requirement is met.

## 11. Backward compatibility

Independently reconfirmed for this ADR (not merely carried over from S0): zero
production Recovery Authority state exists anywhere in this repository or, so far as
this repository's evidence shows, in any deployed environment — no deployable binary,
no bootstrap, nothing ever run against production Spanner.

**Decision:** `EMG-ADR043-COMMITTED-V1` remains supported only for existing
unit-test/qualification fixtures, exactly as they exist today — untouched, unmigrated,
still verifiable under their original schema and domain separator. **Production genesis
uses `EMG-ADR044-COMMITTED-V2` exclusively, from the first record onward.** No
migration tooling is designed or required, because no production state exists to
migrate. A production verifier configuration recognizes only the V2 domain separator;
a V1-shaped record presented where V2 is expected is unrecognized and rejected — there
is no automatic V1/V2 format detection, and no malformed or V1 record may silently fall
through to alternate verification logic (Attack 12, §13).

**Construction-path separation (a first draft of this ADR left this ambiguous, corrected
here).** "V1 fixtures remain unchanged" is only achievable if V1's existing
construction path itself never changes. `NewCommittedPayload`'s existing signature,
behavior, and domain separator (`DomainCommitted` = `EMG-ADR043-COMMITTED-V1`) SHALL
remain byte-for-byte unmodified — every existing call site, including every existing
V1 test fixture, SHALL continue to compile and produce identical output without
modification. The V2 schema (`signing_key_id` included) SHALL be constructed through a
**separate, explicitly-versioned constructor** (e.g. `NewCommittedPayloadV2`, or
equivalent) that produces records under `EMG-ADR044-COMMITTED-V2` only. The two
constructors MAY share underlying representation or helper code where doing so does
not require any V1 call site to change; they SHALL NOT be unified into a single
constructor whose signature differs from `NewCommittedPayload`'s current one. There is
no "upgrade a V1 payload to V2" operation — V1 and V2 are two distinct, independently
constructed record shapes under two distinct, disjoint domain separators, never one
mutated into the other.

## 12. `CommittedCheckpointVerifier` disposition

Independently reconfirmed immediately before drafting this ADR: `recovery/verifier.go`'s
`CommittedCheckpointVerifier` interface and its `VerifyCommitted` method have zero
implementations, zero callers, and zero test references anywhere in
`services/recovery-authority`. It is authorized for **removal** as dead, never-used,
pre-production surface during S1. It is not retained for compatibility, since nothing
has ever depended on it, and retaining unused verification-shaped interfaces alongside
new signing-related surface would itself create exactly the ambiguity a future review
would need to re-disposition later.

## 13. Adversarial threat review

This table incorporates two corrections found during this ADR's own independent
review, before Git checkpoint: the verification trust-anchor (§7A) and the
construction-order fix (§10). Attacks 4, 5, and 16 in the first draft's table were
`DESIGN_GAP` under the uncorrected design and are restated here as `FAIL_CLOSED` against
the corrected design that now ships in this document.

| # | Attack | Result |
|---|---|---|
| 1 | EMG org admin grants self signing rights | **Fail-closed.** Blocked structurally — no IAM path between administratively unrelated domains (§4). |
| 2 | Signing-domain admin mutates Spanner/GCS | **Fail-closed.** Symmetric non-grant (§4, §5). |
| 3 | Signer workload replaced by a malicious signer | **Contained, not absolutely prevented** (disclosed, not overclaimed): cannot reach Spanner/GCS; any rogue signature remains bound to specific content and time and is subject to the same audit/compromise-record exposure as any other signing activity in that domain. |
| 4 | Attacker creates their own valid Cloud KMS key (fully outside EMG's signing trust domain) and sets `signing_key_id` to it | **Fail-closed** (corrected — was `DESIGN_GAP` before §7A). Content binding, digest recomputation, and cryptographic verification can all pass under an attacker's own key, but §7A step 2 (key-authorization/lineage check) independently rejects any `signing_key_id` not belonging to the approved signing lineage, regardless. |
| 5 | `signing_key_id` points to another project/trust domain | **Fail-closed** (corrected — same mechanism as Attack 4, §7A). |
| 6 | `signing_key_id` tampered after signing | **Fail-closed.** Part of the signed digest (§8); tampering changes the recomputed digest and the original signature no longer matches (§7A step 3 vs. step 6). |
| 7 | Unknown `signing_key_id` | **Fail-closed.** Unresolvable identifier is rejected by explicit design (§7A step 2/step 4; §10 requirement 7). |
| 8 | Old, legitimate key routinely rotated out of active signing, disabled *after* its public key was properly pinned per §7C | **Verifies correctly** (§7, §7C). Historical validity is unaffected by disablement because verification uses the pinned public material, never live provider retrieval (which §6's correction confirms stops at disablement, not destruction); new signing correctly excludes the retired version because the caller's own `ActiveKeyID` configuration no longer names it (§6, §10). |
| 9 | Old key compromised after having legitimately signed historical records | **Distinguishable** via the distrust-effective-time comparison against the record's own trusted `commit_timestamp` (§7). Requires the compromise ledger itself to satisfy §7's governance properties (append-only, administratively independent of the signing domain) — explicitly required now, not silently assumed (§7). |
| 10 | Compromise-effective-time is maliciously altered (backdated/forward-dated) | **Fail-closed by required governance property** (§7, property 2 and 4): the ledger must be administratively independent of the signing domain and protected against unilateral backdating by any single administrator, including a compromised signing-domain administrator. The concrete enforcement mechanism is S3+ scope; the requirement itself is binding on that scope as of this ADR. |
| 11 | Compromise-effective-time record is unavailable | **Fail-closed.** §7's fail-closed scope explicitly covers compromise-ledger unavailability — an inability to rule out an undetected compromise is itself a verification failure. |
| 12 | Cloud KMS API unavailable during recovery | **Not required to fail closed for routine historical verification** — routine verification does not depend on live Cloud KMS availability at all once §7C's mandatory pinning is satisfied (corrected: this is no longer an optional recommendation, §7C); compromise-ledger unavailability specifically remains fail-closed regardless (Attack 11). |
| 13 | `CryptoKeyVersion` destroyed before evidence retention expires | **Policy-dependent, disclosed as such** (§6's critical invariant) — a genuine, irreversible governance/production-control failure if it occurs, since destruction (unlike disablement) also makes the provider stop serving the public key to anyone who had not already pinned it. If the retention-gated destruction control fails operationally, the affected records become permanently unverifiable — an honest residual risk, not falsely claimed impossible. |
| 14 | V1 record appears in production | **Fail-closed.** Production verifier recognizes V2 only; no dual-format auto-detection (§11). |
| 15 | V2 record appears in V1 qualification tooling | **Not applicable as a security concern.** V1 qualification tooling is scoped to V1 fixtures only (§11); nothing routes a V2 record there, and doing so is not a meaningful attack surface — the reverse case (Attack 14) is the one that matters and is handled. |
| 16 | Signer's post-signing confirmation names a different key version than the one already bound into the digest | **Fail-closed** (corrected — was `DESIGN_GAP` before §10's construction-order fix). §10 step 7 makes this an explicit, mandatory hard construction failure — no payload is produced. |
| 17 | Signer returns a signature but empty/malformed key ID | **Fail-closed by explicit requirement** (§10 formal requirements 5): treated as signing-operation failure as a whole; `buildCommittedPayload` rejects an empty/unset key ID at any point in the sequence exactly as it already rejects an empty signature. |
| 18 | Attacker substitutes a different, but still *valid*, historical key version within the same approved `CryptoKey` | **Fail-closed** for the external-attacker case — digest binding (§8) prevents substituting any different key-id, valid elsewhere or not, without invalidating the signature. A narrower legitimate-signer-misuse variant (a signing principal authorized for one version using a different, also-legitimate version under the same `CryptoKey`) is a recommended IAM-scoping refinement for S3 (§7B) — not a protocol-level gap. |
| 19 | Old, retired-but-not-compromised key is used to sign a *new* operation | **Not applicable as a protocol-level concern.** Naturally excluded because the caller's own `ActiveKeyID` configuration no longer names the retired version (§6, §10); if the provider itself has disabled the version, `AsymmetricSign` is refused at the provider level as an additional backstop. Using a retired-but-legitimate key would be an operational-hygiene error, not a security hole, since it is not itself marked compromised. |
| 20 | Recovery process attempts to choose the verification key itself | **Fail-closed.** §10 formal requirement 6 requires the verifier use only the payload's own persisted key identifier, never a caller-supplied override; `recovery` still has no path to `Signer` or `acceptedRotationContext` (unchanged from ADR-044). |
| 21 | Key version disabled *before* its public key was pinned (§7C step f/g skipped) | **Operational governance violation, disclosed as such — not silently recoverable.** The affected version's historical records become permanently unverifiable through no protocol defect; §7C requires confirmed pinning as an auditable gate precisely to prevent this from happening silently. The system SHALL NOT auto-re-enable the version merely to attempt recovery — that would itself be a fail-open bypass of §5's key-lifecycle administration boundary. |
| 22 | Pinned public key material is substituted for an existing `SigningKeyID` | **Fail-closed.** §7C requires an integrity binding between `SigningKeyID` and its pinned public key specifically to prevent silent substitution; a substituted pinned key fails that integrity check independent of any other verification step. |
| 23 | Pinned public key is genuine but its provenance cannot be shown to originate from the approved signing lineage | **Fail-closed at key authorization (§7A), independent of pinning.** `PinnedPublicKeyExists` does not imply `KeyAuthorized` (§7C); the lineage check operates on `signing_key_id` regardless of where or how the corresponding public material was sourced. |
| 24 | Signing lineage is superseded (deliberately replaced, never compromised) | **Historical records remain governed by authorization-at-the-time semantics (§7D)** — legitimately verifiable if they were signed while that lineage was the approved one. New signing under the superseded lineage is forbidden; this is a lineage-level analog of the key-level routine-rotation distinction in §7/§7C, not a new mechanism. |

Every attack resolves to an explicit, fail-closed (or explicitly-disclosed-as-bounded
or not-applicable, never silently-assumed-safe) outcome against the corrected design in
this document. No attack was found that the corrected design cannot answer without
further, currently-unresolved research.

## 14. S1 authorization boundary

This ADR authorizes the following, and only the following, as S1 — and only after this
ADR itself is independently reviewed and Accepted:

**S1 allowed scope:**
- add the `protocol.SigningKeyID` validated type;
- add `signing_key_id` to a **new, V2-specific** `CommittedPayload` construction path
  and include it in the V2 `CanonicalDigest` (§11 — `NewCommittedPayload`, V1, remains
  byte-for-byte unmodified; a separate constructor, e.g. `NewCommittedPayloadV2`,
  produces V2 records only);
- add the new, additive `EMG-ADR044-COMMITTED-V2` domain separator;
- update the `Signer` interface to add `ActiveKeyID` and the confirming `keyID` return
  on `SignCommittedDigest`, per §10;
- update the `CommittedSignatureVerifier` interface to add `keyID` and `signedAt`, per
  §10;
- update `buildCommittedPayload` to implement the corrected §10 construction sequence
  in full: call `ActiveKeyID` before building the digest, bind the returned key-id into
  the V2 payload, compute the digest, sign, and hard-fail (produce no payload) on any
  mismatch between the pre-bound and post-signing-confirmed key-id (§10 steps 1–8);
- add an approved-signing-lineage field to `ExpectedBinding` and the corresponding
  independent key-authorization check to `VerifyPersistedCommitted`, per §7A — this
  check is mandatory and MUST be implemented in S1, even though the concrete signing
  lineage's real value is only meaningfully populated once S3 exists; S1 SHALL supply
  the mechanism and MUST NOT ship `VerifyPersistedCommitted` without it, per §7A's
  mandatory verification sequence;
- update `VerifyPersistedCommitted` to pass the persisted key-id and commit timestamp
  through to the verifier, and to perform the key-authorization check *before* trusting
  any downstream cryptographic result (§7A);
- update `conformance/localsigner` so existing emulator-tier tests keep compiling and
  exercise the new shape, including: a second test keypair to exercise
  rotation/cross-key-mismatch cases; an `ActiveKeyID` implementation; and a
  deliberately-mismatched-key-id test double to exercise §10 step 7's hard-failure
  path;
- remove `recovery/verifier.go`'s `CommittedCheckpointVerifier` (§12);
- add the full test matrix specified in §18.

**S1 MUST NOT:**
- implement a production KMS/Signer adapter (S3);
- create any signing project, key, service account, or IAM binding (no GCP access at
  all);
- implement the compromise-record/distrust-ledger mechanism itself, or its
  administrative-independence enforcement (S3+; S1 only makes the interface shape
  accommodate it, per §7 and §10);
- populate the approved-signing-lineage value with any real, production-meaningful
  identity — a placeholder/test-only value in `ExpectedBinding`'s test fixtures is
  sufficient for S1; the real value is an S3+/deployment-configuration concern;
- change IAM anywhere;
- implement the production Spanner adapter (S2 — a separate, unrelated track);
- modify any existing `EMG-ADR043-*` domain separator;
- modify `NewCommittedPayload`'s existing (V1) signature, behavior, or any existing V1
  fixture;
- modify any historical evidence file;
- deploy anything.

## 15. Consequences

- Closes ADR-044 §17 items 9 (signing administrative independence) and 10 (key
  lifecycle/historical verification) at the architecture-decision level; their
  implementation and qualification remain separate, subsequent work (S1 for the
  protocol shape, S3+ for the concrete signing adapter and compromise-record
  mechanism).
- Corrects four defects found across this ADR's own drafting and independent-review
  process before any code was written, at zero implementation cost: S0's over-strict
  disabled-key rule (§7); a missing verification trust anchor that would otherwise have
  reintroduced an acceptance-provenance bypass (§7A); a circular digest/signing
  construction order that would have made S1 non-implementable as first drafted (§10);
  and a factual error about Cloud KMS's disabled-key public-key retrievability,
  independently re-verified against current official documentation, that would have
  left the §7 correction's own central claim unsupported without §7C's mandatory
  pinning requirement. No interface shipped, and no code was written, under any of the
  four incorrect assumptions.
- Elevates public-key pinning (§7C) from an optional S3 recommendation to a mandatory
  architectural requirement — a documentation-only correction with zero impact on the
  `Signer`/`CommittedSignatureVerifier` interface shapes already specified in §10, since
  pinning is an implementation detail entirely behind the verifier boundary.
- Adds exactly one new, additive protocol constant; changes no existing one.
- `recovery/verifier.go` loses one dead interface.
- `ExpectedBinding` gains one new mandatory field (approved signing lineage);
  `VerifyPersistedCommitted` gains one new mandatory, independent check.
- No GCP resource, IAM policy, or credential is created by this ADR.

## 16. Relationship to ADR-044 and ADR-043

This ADR **extends** ADR-044 by resolving two items ADR-044 itself explicitly reserved
(§15A's trust-domain selection; §17 item 10's key-lifecycle design) — it does not
reopen, redesign, or weaken any already-accepted ADR-044 invariant. ADR-044's Spanner
authority model (§5, §8), witness model (§6), and content-binding/acceptance-provenance
separation (§7) are unchanged; this ADR's only protocol-level effect is the additive
V2 extension described in §8–§9. **This ADR is not an amendment to ADR-044** — per the
same reasoning ADR-044 itself applied when it chose a new number rather than amending
the unrelated Identity ADR-043 (a distinct, subsequent decision on a separable
question, following this repository's established pattern of numbering forward rather
than reopening an accepted document), this ADR receives its own number. ADR-044's own
text is not modified by this document.

This ADR has **no effect whatsoever** on Identity ADR-043
(`EMG_ADR-043_IDENTITY_DURABLE_REFRESH_STATE_DATABASE_AND_MIGRATION_AUTHORITY.md`),
which remains completely separate, Accepted, and untouched.

## 17. Rejected alternatives

- **Same-organization signing construction (Option C).** Rejected on security grounds
  — does not close the row-G threat as modeled (§4).
- **External HSM/signing service (Option B).** Not selected as the default — adds
  delivery/operational cost without a required security property Option A lacks;
  remains available as a future alternative if a concrete requirement Option A cannot
  meet is identified (§4).
- **"Current key only" verification.** Rejected — explicitly prohibited by ADR-044 §17
  item 10 and would make legitimate historical evidence permanently unverifiable after
  ordinary rotation.
- **Unsigned/out-of-band key identifier.** Rejected — decouples key attestation from
  the content it authenticates (§8).
- **Verifier that tries all historical keys.** Rejected — ambiguous historical
  verification, unbounded trial-and-error, contrary to this protocol's
  single-linearization-point discipline (§8).
- **Treating any disabled key as automatically invalid for historical verification.**
  Rejected — this was S0's own initial position, corrected in §7 after adversarial
  review found it would make legitimate historical evidence permanently unverifiable
  after every ordinary rotation, conflating routine key-lifecycle state with compromise
  governance.
- **Amending ADR-044 directly instead of a new ADR.** Rejected — ADR-044 explicitly
  reserved this decision as separate, subsequent work; amending it directly would
  reopen an Accepted document for a decision it already anticipated and deferred.
- **Treating cryptographic binding of `signing_key_id` as sufficient trust on its
  own, with no independent key-authorization check.** Rejected — this was this ADR's
  own first-draft position, corrected in §7A after independent review found it would
  allow any actor possessing any valid signing key anywhere, including a fully
  unrelated attacker-owned key, to construct an internally self-consistent, fully
  verifiable forged record. Binding prevents tampering with an already-legitimate
  value; it does not establish that the value was ever legitimate.
- **Discovering `signing_key_id` only from the signing call's return value, after the
  digest is already computed.** Rejected — this was this ADR's own first-draft
  interface design, corrected in §10 after independent review found it circular and
  non-implementable: the digest cannot legally include a value not yet known at the
  time it is computed. The key identifier must be determined before signing and
  confirmed, not originated, afterward.
- **Relying on live Cloud KMS `GetPublicKey` retrieval as the mechanism preserving
  historical verifiability across routine key rotation, with public-key pinning
  treated as an optional S3 hardening recommendation.** Rejected — this was this ADR's
  own first-draft position, corrected in §6/§7/§7C after independent review, verified
  against current official Cloud KMS documentation, found that live retrieval stops at
  disablement (not destruction as first assumed): "you can retrieve a key version's
  public key only if the key version is enabled." Without mandatory pinning, the
  document's own central §7 correction — that routine rotation must not break
  historical verifiability — would not actually hold for the selected provider.
  Pinning is now a required architectural property (§7C), not an optional one.

## 18. Qualification requirements

**S1 test matrix — required, at minimum:**

1. V1 digest fixtures remain byte-identical (no change to any existing computed
   digest value).
2. V1 constructor (`NewCommittedPayload`) behavior remains unchanged — every existing
   call site continues to compile and produce identical output.
3. V2's `signing_key_id` changes the V2 digest (differs from an otherwise-identical
   payload with a different key-id).
4. The signature itself remains excluded from `CanonicalDigest` under V2, exactly as
   under V1.
5. A tampered `signing_key_id` (post-signing modification) fails verification.
6. An unknown/unresolvable `signing_key_id` fails verification.
7. A cryptographically valid signature from an attacker-owned key outside the approved
   signing lineage fails verification (§7A — the key-authorization check, exercised
   independently of cryptographic validity).
8. An approved historical key verifies correctly after routine rotation (disabled for
   new signing, still valid for history).
9. A key-id returned/confirmed by the signer that differs from the key-id already
   pre-bound via `ActiveKeyID` causes a hard construction failure — no payload is
   produced (§10 step 7).
10. An empty or malformed `SigningKeyID` fails construction, at any point in the
    sequence.
11. A V1 record is rejected by V2-only production verification configuration.
12. A V2 record is not silently interpreted as V1 by V1-scoped tooling.
13. A record whose `commit_timestamp` is at or after a declared compromise
    distrust-effective-time is not auto-accepted (§7).
14. A record whose `commit_timestamp` is strictly before a declared
    distrust-effective-time remains governed by the explicitly documented policy (§7)
    — verifiable, not silently treated as compromised merely because the key was later
    distrusted.
15. Compromise-ledger unavailability at verification time cannot result in silent
    verification success (§7's fail-closed scope).
16. No code path in `recovery` gains, or can be made to gain, signing capability —
    re-verified unaffected by this ADR's changes.

**Before S1 code may be considered complete:** the full matrix above passes, in
addition to the digest-disjointness and rotation/cross-key-mismatch coverage already
implied by §13's attack table.

**Before S3 (the concrete signing adapter) may be considered complete:** the selected
trust-domain realization's actual administrative independence must be independently
verified against current GCP documentation and, where feasible, empirically qualified
(mirroring the rigor ADR-044's own real-GCP Bucket Lock qualification applied) — not
assumed from this ADR's architecture-level description alone (§4); the compromise
ledger's §7 governance properties (append-only, administratively independent,
auditable, backdating-resistant) must be verified against its concrete realization; and
the approved-signing-lineage value populated into `ExpectedBinding` in production
configuration must itself be independently, out-of-band verified as correct before
first production use.

**S3 pinned-public-key qualification — required, at minimum (§7C):**

1. The public key can be retrieved while the signing version is `ENABLED`.
2. The exact retrieved public key is durably pinned, indexed by its `SigningKeyID`.
3. The pinned public key independently, correctly verifies a signature genuinely
   produced by that exact version (round-trip qualification, not assumed).
4. After routine disablement of the version, historical verification continues to
   succeed using the pinned material alone — exercised as a real test, not inferred.
5. New signing does not use the disabled version (provider-enforced, confirmed as a
   backstop rather than solely relied upon).
6. A different public key substituted under an already-pinned `SigningKeyID` is
   rejected by the pinned-key integrity check (Attack 22, §13).
7. A public key from another `CryptoKey`, project, or trust domain is rejected by the
   approved-lineage check (§7A) regardless of pinning status (Attack 23, §13).
8. Missing pinned public material for a disabled historical key fails closed — never
   silently treated as "not yet compromised, therefore acceptable" (Attack 21, §13).
9. Compromise-ledger policy still overrides an otherwise-valid pinned-key cryptographic
   verification (§7, unaffected by this correction).
10. Scheduled-for-destruction and destroyed lifecycle states are exercised or
    explicitly governed before production approval, including the required
    pre-destruction pinning-confirmation gate (§7C step f).

These are S3 qualification requirements. They do not add to S1's implementation scope
(§14) — S1 implements no key retrieval, pinning, or storage logic; it implements only
the protocol/interface shape that a pinning-aware verifier will later be built behind.

## 19. Production approval boundary

**`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED.`** This ADR's eventual acceptance
ratifies a protocol/architecture decision only. It does not authorize production
deployment, does not create any GCP resource, does not complete any ADR-044 §17
production prerequisite beyond the two design-level items it resolves, and does not
change ADR-044 §22's requirement that a separate, explicit production-approval decision
follow independent implementation and qualification of every §17 item.

---

## Appendix A — S0 assumptions independently re-verified before this draft

| Assumption | Verified |
|---|---|
| No `signing_key_id`/`SigningKeyID` exists anywhere in the service | Confirmed — zero matches |
| No key registry exists | Confirmed — zero matches |
| `CommittedSignatureVerifier` assumes exactly one implicit key | Confirmed — no key parameter in current signature |
| `Signer.SignCommittedDigest` returns only a signature | Confirmed — current signature has no key-id return |
| `CommittedCheckpointVerifier` has zero implementations/callers | Confirmed — only its own declaration exists in the repository |
| No production Recovery Authority state, binary, or KMS integration exists | Confirmed — no `main.go`/`cmd/`, no KMS import anywhere |
