# Recovery Authority — Administrative Independence Decision Package (Track G)

**Status: PROPOSED / AWAITING HUMAN GOVERNANCE APPROVAL.** This document is
a governance decision *package* for a human approval body to review and
act on — it is not itself an approval, does not amend ADR-044, ADR-045, or
Identity ADR-043, creates or provisions no GCP resource, organization,
Cloud Identity domain, or billing account, and does not authorize
production provisioning, production genesis, or production approval.
Nothing in this document becomes effective until a named human governance
body explicitly approves it in writing, at which point this status line
should be updated to reflect that approval and who granted it — never
silently.

**Derived from:** ADR-044 §14 row G, §15, §15A, §17 item 9; ADR-045 §4, §5,
§7, §7A; `RECOVERY_AUTHORITY_PLACEMENT_AND_BILLING_GOVERNANCE_DECISION.md`
§4, §9 (which already selected ADR-045 §4's "Option A" and already
independently reconfirmed, against current official GCP documentation, that
production requires a genuinely separate Cloud Identity/Workspace
administrative domain — this document does not re-decide that selection;
it operationalizes it into a concrete decision package).

## G1 — Target production topology

### Domain A — Authority/Witness

| Element | Requirement |
|---|---|
| Cloud Identity/Workspace organization | The existing EMG organization (unchanged) |
| Project(s) | One or more projects hosting the Spanner authority database and the GCS Bucket-Locked witness bucket |
| Administrators | Authority/witness administrators per ADR-044 §15's role list — MUST NOT include lien-removal, project-deletion, billing-link, retention-policy administration, or organization administration in the *runtime* principal |
| Billing | Separate billing account is the recommended default (per the existing placement/billing decision record §5.2); shared billing requires an explicit, separately recorded risk acceptance |
| Spanner | The authority database, real Bucket-Locked witness bucket, `authority_head`/`authority_transition_history` tables |
| Runtime identities | `recovery-authority-runtime`, `recovery-verification-read` (already defined, `iam/manifest.json`) |

### Domain B — Signing

| Element | Requirement |
|---|---|
| Cloud Identity/Workspace administrative root | **Must be genuinely independent — a separate Cloud Identity/Workspace administrative domain, not merely a second `organizations` resource under the current Workspace.** This is the precise point ADR-045 §4 leaves to "a separate, subsequent implementation-review decision" (§17 item 9) — this document is that decision's proposal, not its final approval. |
| Administrators | Non-overlapping human administrators from Domain A — no individual may hold standing administrative rights in both domains |
| Signing project | Hosts the Cloud KMS key ring/key/version |
| Signer runtime | `cmd/recovery-signer`, the sole holder of `AsymmetricSign` capability |
| Pin store | `keypinning.GCSStore`'s bucket — administered by the signing domain (per that package's own doc comment), never by Domain A |
| Break-glass owners | Independently governed, auditable, distinct from ordinary signing-key administration (ADR-045 §5) |
| WIF/invocation model | Workload identity federation binding `recovery-signer`'s Kubernetes service account to its GCP signing identity, scoped to exactly the `AsymmetricSign` permission on the specific key |

### Domain C — Compromise Ledger

**Recommended default: Option A — a third independent administrative domain**, distinct from both A and B, matching `compromiseledger.GCSLedger`'s own already-written doc comment ("the `gcswitness.Adapter` this type is constructed with in production MUST be bound to a bucket in a THIRD administrative domain"). This is the strongest reading of ADR-045 §7's five governance properties (append-only, administratively independent of ordinary signing-domain administration, auditable, backdate/suppress-resistant, readable without signing capability) and is what the landed code already assumes.

**Option B — an independently governed project inside Domain B**, with segregated IAM such that ordinary signing-key administrators cannot reach the ledger, is architecturally *permitted* by ADR-045 §7's literal text ("at minimum, the same governance tier as break-glass") but is a weaker alternative the current code does not assume and would require its own explicit, separately recorded risk-acceptance decision if chosen instead of Option A — exactly the pattern the existing billing-placement decision record already establishes for a comparable choice.

**Option C — an equivalent externally governed immutable system** (outside GCP entirely) is not selected and not excluded; it would require its own separate technical evaluation.

**This document selects nothing silently: it recommends Option A and names Option B as the disclosed, weaker fallback requiring its own risk acceptance if chosen.**

## G2 — Human/administrative separation matrix

| Role | Can administer | Must not administer | Can approve | Cannot self-grant | Audit requirement |
|---|---|---|---|---|---|
| AUTHORITY_ORG_ADMIN | Domain A (Spanner, witness bucket, its IAM) | Domain B, Domain C | Domain A changes | Signing capability, ledger-write capability | Every IAM change logged |
| SIGNING_ORG_ADMIN | Domain B (KMS, signer runtime, pin store) | Domain A, Domain C | Domain B changes, key rotation | Domain A mutation capability, ledger-write capability | Every key-administration and signing operation logged (ADR-045 §5) |
| LEDGER_ADMIN | Domain C (compromise ledger write access) | Domain A, Domain B | Compromise declarations only | Domain A/B capability; cannot edit/delete own past entries (append-only) | Every ledger write is itself an audited event (ADR-045 §7 property 3) |
| BREAK_GLASS_APPROVER | Nothing standing — only a time-boxed, just-in-time grant within Domain B | Domain A, Domain C, any standing Domain B grant | Emergency signing-capability grants only, under quorum | Cannot approve their own request | Full audit trail; independent post-use review (ADR-045 §5) |
| BILLING_ADMIN | Billing account linkage | IAM, KMS, or storage resources of any linked project (independently reconfirmed: Cloud Billing accounts are not IAM parents of linked projects) | Billing account changes | N/A — billing has no IAM reach by design | Billing-account-level actions logged |
| SECURITY_REVIEWER | Nothing (read-only across all domains for review purposes) | Any standing administrative capability | Sign off on IAM-inheritance review (G5) | N/A | Review findings recorded |
| PRODUCTION_BOOTSTRAP_APPROVER | Nothing standing — approves the temporary `recovery-bootstrap-deployment` principal's activation window | N/A | Genesis/bootstrap execution window | Cannot also be the executing operator alone (dual control, per `bootstrap.GenesisRequest`'s existing `Approval` mechanism) | Approval recorded in genesis evidence |
| PRODUCTION_RELEASE_APPROVER | Nothing standing | N/A | Final production approval (ADR-044 §22) | Cannot be any of the above roles simultaneously | Approval decision recorded, dated, named |

No individual names are assigned by this document — only role definitions, per this task's explicit instruction.

## G3 — Cloud Identity/Workspace decision

**Human governance must approve, precisely:**

1. **A genuinely separate Cloud Identity/Workspace administrative root for Domain B** — not a project, not a folder, not a second GCP `organizations` resource nested under the same Workspace/Cloud Identity account. "Separate project" alone is explicitly insufficient and is not what this document asks for.
2. **A distinct Super Admin population** for that separate Workspace/Cloud Identity root — no individual holding Super Admin in the existing EMG Workspace may also hold it in the new one.
3. **Distinct account-recovery channels** (recovery email/phone, recovery codes) for the new root's administrators — sharing a recovery channel with Domain A's administrators would allow an account-recovery path to cross the boundary this domain split exists to create.
4. **Distinct MFA/credential ownership** — separate hardware security keys or authenticator enrollments, not shared devices or shared password-manager vaults, for Domain B's administrators.
5. **Distinct break-glass credentials** for Domain B, stored and governed independently of Domain A's own break-glass material.

**ARCHITECTURE_REQUIREMENT (mandated by ADR-045 §4/§15A):** items 1 and 2.
**RECOMMENDED_HARDENING (not independently mandated by the ADR text, but necessary in practice to make items 1–2 actually hold under a real incident):** items 3, 4, 5 — a "separate" administrative root whose recovery channel, MFA devices, or break-glass credentials are shared with Domain A is not genuinely independent in practice, regardless of its nominal Cloud Identity boundary.

## G4 — Billing

Per the existing, already-approved governance rule (`RECOVERY_AUTHORITY_PLACEMENT_AND_BILLING_GOVERNANCE_DECISION.md` §5.2, §9): **separate billing account is the recommended default** for every Recovery Authority component, including the new signing domain; **shared billing is permitted only via an explicit, separately recorded risk-acceptance decision** naming which account is shared and with which environment. This document does not re-decide that rule — it applies it to Domain B specifically, which the existing document had already anticipated ("a future signing-domain project if realized inside the same GCP organization"). **Billing account placement does not, by itself, provide or substitute for administrative independence** — independently confirmed against current official Google Cloud Billing documentation (a Billing Account Administrator role grants no IAM/KMS/storage reach into a linked project) — this is restated here to prevent billing separation from ever being mistaken for satisfying G1/G3's requirements.

## G5 — IAM inheritance review procedure

To be executed only after Domain A, B, and (if Option A) C's real project/organization hierarchy exists — this document defines the procedure, performs none of it:

1. For every project in every domain, enumerate all IAM bindings at the project level and every ancestor (folder, organization) using `gcloud projects get-ancestors-iam-policy`-equivalent tooling, and confirm no `roles/owner`, `roles/editor`, or other broad role is bound to any principal reachable from another domain.
2. Confirm no organization-level or folder-level binding grants any `cloudkms.*` permission to a principal outside Domain B.
3. Confirm no organization-level or folder-level binding grants any `spanner.*` or `storage.*` permission (on Domain A's or C's resources) to a principal outside their own domain.
4. For every service account in Domain B, confirm no principal in Domain A or C holds `iam.serviceAccounts.getAccessToken`, `.actAs`, `.signBlob`, or `.signJwt` on it (cross-domain impersonation).
5. Confirm no single IAM group or Google group has membership spanning administrators of more than one domain.
6. Confirm any IAM Deny policy relied upon to enforce the boundary is itself correctly scoped and cannot be overridden by a principal outside the domain it protects.
7. Confirm no principal outside Domain B holds `iam.serviceAccountKeys.create` on any Domain B service account.
8. Confirm no principal outside its own domain holds `roles/iam.serviceAccountTokenCreator` or equivalent `actAs` capability, except where explicitly required and separately justified (e.g., the existing `recovery-authority` → `recovery-signer` WIF-mediated call path, already narrowly scoped).
9. Walk every project's full ancestor chain (project → folder → organization) and confirm no ancestor-level grant reintroduces a forbidden capability at any level — `iam/manifest.json`'s own Attack K explicitly and honestly states this cannot be disproven by the manifest alone and requires exactly this real-hierarchy review.

This procedure must be independently executed by SECURITY_REVIEWER (G2) and its findings recorded as part of the eventual production approval review package (G7).

## G6 — Break-glass

- **Who may request:** Any designated Domain B on-call signing administrator, or a designated incident commander, when normal signing capability is unavailable or a compromise is suspected.
- **Who must approve:** At least one BREAK_GLASS_APPROVER independent of the requester and independent of ordinary Domain B administration (ADR-045 §5's independence requirement).
- **Minimum quorum:** Two independent approvers, neither of whom is the requester.
- **Duration:** Time-boxed grant, no longer than the specific incident's operational window (recommended default: 4 hours, renewable only via a fresh approval).
- **Just-in-time binding:** Capability granted only for the approved window, via a temporary IAM binding — never a standing credential.
- **Audit log:** Every break-glass request, approval, grant, and use is logged as its own auditable event (ADR-045 §5).
- **Automatic expiry/removal:** The temporary binding is automatically revoked at window end without requiring a further manual action (mirroring `recovery-bootstrap-deployment`'s already-implemented temporary-then-revoked pattern).
- **Post-use review:** A mandatory post-incident review confirms the grant was used only for its stated purpose and records findings for the compromise ledger if warranted.
- **No permanent cross-domain break-glass grant** is ever permitted under any circumstance.

## G7 — Production provisioning go/no-go checklist

To be completed and explicitly signed off by human governance before any production resource in Domain A, B, or C is created:

- [ ] Independent signing administrative root (G3 items 1–2) approved
- [ ] Independent administrators assigned, with non-overlapping recovery/MFA/break-glass credentials (G3 items 3–5)
- [ ] Compromise-ledger domain model (Option A vs. B) approved, with risk acceptance recorded if Option B is chosen
- [ ] Billing topology (separate-by-default or explicit shared-risk-acceptance) approved for every domain
- [ ] Break-glass procedure (G6) approved
- [ ] IAM-inheritance review method (G5) approved as the procedure to run once real infrastructure exists
- [ ] Production project names/resource placement approved
- [ ] Irreversible Bucket Lock creation on the production witness bucket explicitly approved (retention locking is permanent — ADR-044 §11/§17 item 8)
- [ ] KMS key lifecycle owner (rotation, disablement, compromise response, per ADR-044 §17 item 10) designated
- [ ] Bootstrap/genesis approvers (dual control, `bootstrap.Approval`) designated

**No production resource provisioning may occur before every item above is explicitly checked and approved by named human governance roles** (not merely by this document's existence). Provisioning infrastructure under this checklist still does not authorize production genesis or production approval — those remain separately gated per ADR-044 §22 and the production bootstrap/genesis preconditions already defined in the prior Production Readiness report.

## What this document does not do

- Does not create, modify, or provision any GCP project, organization, Cloud Identity/Workspace domain, billing account, or IAM binding.
- Does not select Option B or C for Domain C — it recommends Option A and names the alternatives' disclosed trade-offs.
- Does not grant risk acceptance for any specific shared-billing deployment.
- Does not close ADR-044 §17 item 9 — that remains open until a concrete signing trust domain satisfying this package (once approved) is actually provisioned and independently qualified (G5).
- Does not authorize production provisioning, production genesis, or production approval under any circumstance.
