# Recovery Authority — Placement and Billing/Organization Governance Decision

**Status:** Governance decision record, not an architecture decision record. Creates,
authorizes, and provisions no GCP resource, organization, folder, project, or billing
account. Records a decision about where such resources should eventually be placed and
under what conditions, for use when S4–S7 implementation begins.
**Derived from:** ADR-044 §15, §15A, §17 items 8 and 9; ADR-045 §4, §5, §7 (property 2).
**Does not amend** ADR-044, ADR-045, or Identity ADR-043.

## 1. Purpose

ADR-044 §17 lists two unresolved placement/governance items that block production
approval: item 8 (the witness project's billing-account boundary) and item 9
(implementation and qualification of ADR-045's signing administrative independence
requirement). This document records the governance decision for both, addressed
together because they are two instances of the same underlying question — which
administrative and financial domain each Recovery Authority component should sit in —
without inventing new architecture beyond what ADR-044 and ADR-045 already specified.
It selects among **already-authorized** options; it does not authorize a new one.

## 2. The three domains in question

Per ADR-044 §15 and ADR-045 §4–§5, Recovery Authority spans at least three logically
distinct administrative domains. This section states what each domain is; §3–§5 decide
how each should be placed.

1. **Spanner/GCS authority-and-witness domain** — the project(s) hosting the Spanner
   authority database and the GCS Bucket-Locked witness bucket. Administered by the
   Recovery Authority's own authority/witness administrators (ADR-044 §15).
2. **Signing administrative trust domain** — the key material, its IAM policy, and the
   workload/service identity permitted to invoke it (ADR-045 §4–§5). ADR-045 §15A
   requires this domain be administratively independent from whoever administers
   domain 1, if the threat model includes a compromised organization administrator
   over domain 1 (ADR-044 §14 row G) — which it does; §14 row G is not framed as an
   accepted risk, it is framed as open until §15A is satisfied.
3. **Witness-project billing account** — the Cloud Billing account associated with
   domain 1's project(s). Distinct from, though related to, domain 1's administrative
   boundary: two projects can share a billing account while having different IAM
   administrators, and vice versa.

## 3. Decision — Spanner/GCS authority-and-witness domain

No change from ADR-044. This domain's administrators must not include lien-removal,
project-deletion, billing-link, retention-policy administration, or organization
administration in the *runtime* principal (ADR-044 §15) — that separation is already
decided and is not reopened here. This document adds no new requirement to domain 1
beyond what ADR-044 §15 already specifies.

## 4. Decision — signing administrative trust domain

**Selects ADR-045 §4's "Option A": an independently administered GCP-native signing
trust domain**, as ADR-045 already recorded (ADR-045 §3–§4, and the architecture
decision register's ADR-045 row: "selects an independently administered GCP-native
signing trust domain..., rejects a same-organization-only construction as insufficient
to close the row-G organization-administrator threat"). This document does not
re-decide that selection; it restates it here because it is the second half of the
same placement question this document exists to answer, and because ADR-044 §17 item 9
frames it as a production blocker this decision record should track alongside item 8,
not separately from it.

**What remains open, and is not decided by this document either:** the concrete
realization of that independent domain (a separate GCP organization; an external
HSM/signing service outside the GCP organization entirely; or an org-policy-enforced,
separately-owned folder/project the Spanner/GCS administrators structurally cannot
reach) is explicitly left unselected by ADR-045 §4 pending a "separate, subsequent
implementation-review decision." This document does not make that selection — doing so
without S3's actual implementation in hand would be premature, and ADR-045 is explicit
that it is not authorized here. **Whoever performs S3 must bring a concrete realization
proposal back for review against ADR-045 §15A's five properties before production
approval, not infer authorization to pick one from this document.**

## 5. Decision — witness-project billing account

### 5.1 What the evidence actually shows

The ADR-043 destructive-qualification trials (§13's project-deletion/restore/relink
sequence) were run with the witness project's billing account **shared with
`emg-platform-staging`** (ADR-044 §17 item 8). Every artifact in
`docs/evidence/adr-043/real-gcp-destructive-qualification/` confirms: bucket and object
metadata were byte-identical before deletion, immediately after restore (while billing
was still disabled), and after billing re-link — retention, generation, and hash all
survived the entire billing-disabled window unchanged. **Billing-account placement did
not affect cryptographic integrity, Bucket Lock enforcement, or object survival in this
trial** — those properties held throughout, independent of billing-account sharing.

**What the shared billing account did demonstrably cause:** the billing-disabled window
itself was an *availability* dependency (ADR-044 §13, §14 row F) — object reads were
blocked (`403`) until the shared account's association was explicitly restored. This is
real, evidenced operational coupling between the witness project and whatever else
shares its billing account, not a hypothetical concern. It is not evidence that shared
billing is unsafe from an integrity standpoint; it is evidence that shared billing is an
availability/blast-radius coupling, exactly as ADR-044 §17 item 8 already characterized
it.

**This document makes no claim that a separate billing account is cryptographically
required.** It is not. The claim is narrower and evidence-grounded: shared billing is a
proven availability-coupling vector, and the appropriate governance response to a proven
(not hypothetical) coupling is to require it be a deliberate, recorded decision rather
than an inherited default.

### 5.2 Decision

**Recommended default: a separate billing account for the production witness project**,
isolated from `emg-platform-staging` and from any other environment whose incidents
should not be able to (even indirectly, via a billing-account-level action affecting a
shared project) affect witness availability. This is a blast-radius/isolation
recommendation, not a cryptographic-integrity requirement — restated to prevent this
decision from being cited later as claiming something the evidence does not show.

**If a shared billing account is chosen instead** (for cost, operational-simplicity, or
other reasons outside this document's scope to evaluate), that choice SHALL be an
explicit, separately recorded risk-acceptance decision — naming which account is
shared, with which other environment(s), and accepting the demonstrated
availability-coupling risk in writing — never an accidental default inherited from
qualification-environment convenience, exactly as ADR-044 §17 item 8 already requires.
**This document does not itself grant that risk acceptance for any specific production
deployment** — it defines the requirement that such acceptance, if made, must be
explicit and recorded; a future deployment decision must still produce that record
itself.

### 5.3 Non-decision

This document does not select, provision, or name any specific billing account,
project ID, or organization for production use. No such resource exists yet. This
section closes ADR-044 §17 item 8 as a *governance requirement* (separate-by-default,
explicit-risk-acceptance-if-shared), not as a *provisioning* decision — provisioning is
S6's scope, not this document's.

## 6. Staging/production billing coupling — general principle

Beyond the witness project specifically: any Recovery Authority component (Spanner
authority database project, GCS witness project, or a future signing-domain project if
realized inside the same GCP organization per ADR-045 §4's "same-organization
deployment is not ruled out" allowance) that shares a billing account with
`emg-platform-staging` or any other non-production environment inherits the same
availability-coupling risk class demonstrated in §5.1, and is subject to the same §5.2
default-separate/explicit-risk-acceptance-if-shared requirement. This generalizes the
witness-specific finding rather than treating it as unique to GCS.

## 7. What this document does not do

- Does not provision any GCP project, organization, folder, or billing account.
- Does not select a concrete realization of the independent signing trust domain
  (§4) — that remains S3's responsibility, reviewed separately.
- Does not grant risk acceptance for any specific future shared-billing deployment —
  it defines the requirement that such acceptance be explicit and recorded, for
  whoever makes that deployment decision to actually produce.
- Does not change ADR-044 §17's status as a list of unimplemented production
  prerequisites; items 8 and 9 remain open until S3–S7 exist and this document's
  requirements are satisfied against their concrete implementation.

## 8. Relationship to other documents

Tracks ADR-044 §17 items 8 and 9 and ADR-045 §4/§15A. Does not amend any of them. Should
be revisited once S3 (concrete signing-domain realization) and S6 (bootstrap/
provisioning, including actual billing-account selection) exist, to confirm the
concrete implementation actually satisfies §4 and §5 above rather than merely citing
this document.

## 9. Tiered placement decision (post-S6 review)

This section is the revisit §8 anticipated, performed after S6 (bootstrap/provisioning)
landed and a dedicated read-only signing-domain placement review was conducted against
the real, current GCP resource hierarchy visible to this project's credentials. **It
records a decision within the scope §4 already reserved to "a separate, subsequent
implementation-review decision" — it does not reopen, amend, or weaken ADR-044 or
ADR-045, and it selects among options §4 already authorizes (Option A), never a new
one.** No GCP project, organization, folder, or billing account was created by this
review or by recording this decision.

**Disposable qualification.** A separate, standalone GCP project may be used under the
currently available billing account for mechanism qualification only (proving Cloud KMS
sign/pin/WIF mechanics work) — never as evidence that ADR-045 §15A's administrative
independence property is satisfied. This mirrors how `emg-adr043-disposable-witness` was
already used for the ADR-044 real-GCP Bucket Lock qualification.

**Staging.** A separate, non-production signing project may exist under the current
administrative environment (same organization, same billing account permitted) for
staging rehearsal. This explicitly does **not** prove ADR-045 production administrative
independence, exactly as `infra/environments/staging`'s own README already declines to
claim production-equivalent security guarantees for anything it renders.

**Production.** The signing trust domain must ultimately reside under a genuinely
independent Cloud Identity/Workspace administrative domain — not merely a second
`organizations` resource under the current Workspace — with non-overlapping human
administrators from the authority/witness domain. §4's own reasoning is the basis for
this: a genuine Cloud Identity organization-level administrator retains the ability to
modify org policies and IAM-Deny constraints that any same-organization folder/project
separation depends on, so only a genuinely separate administrative domain (or Option B,
external to GCP entirely) closes ADR-044 §14 row G's organization-administrator threat
as modeled. This was independently re-confirmed against current official Google Cloud
IAM/Resource Manager documentation during the review this section records, per §4's own
verification requirement.

**Billing.** A separate billing account is **not** cryptographically or
administratively necessary for signing-domain independence — independently verified
against current official Google Cloud Billing documentation: Cloud Billing accounts are
not IAM parents of the projects linked to them, and a Billing Account Administrator role
grants no permission over a linked project's own IAM, Cloud KMS, or storage resources.
This confirms and extends §5.1's own finding (that shared billing caused only an
availability coupling, never an integrity/IAM-reach one) to the signing-domain placement
question specifically. The production default therefore remains isolated billing per
§5.2, unless an explicit, separately recorded risk-acceptance decision states otherwise
— never required for administrative independence itself, but still the recommended
default for availability/blast-radius isolation.

**What this section does not do.** It does not select, provision, or name any specific
project, organization, or billing account for any tier. It does not close ADR-044 §17
item 9 — that remains open until a concrete signing trust domain is actually
provisioned and independently qualified against §15A's five properties, which is real-
cloud qualification work explicitly not performed or authorized here.
