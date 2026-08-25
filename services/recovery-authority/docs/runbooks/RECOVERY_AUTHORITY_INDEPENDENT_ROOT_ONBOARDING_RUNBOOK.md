# Recovery Authority — Independent Administrative Root Onboarding Runbook

**Status: ONBOARDING PACKAGE — not itself an approval, and not a record that
any root has been created.** This document tells the human/business owner
exactly what to create for Domain B (Signing) and Domain C (Compromise
Ledger), and tells engineering exactly what to verify once they have. It
does not create any GCP project, organization, Cloud Identity/Workspace
account, billing account, IAM binding, Kubernetes object, or production
resource. It does not amend ADR-044 or ADR-045. It cross-references, and
does not duplicate, `RECOVERY_AUTHORITY_ADMINISTRATIVE_INDEPENDENCE_DECISION_PACKAGE.md`
(Gate A governance decision, APPROVED) and
`RECOVERY_AUTHORITY_PRODUCTION_PROVISIONING_PLAN.md` (resource plan,
Domain B/C marked `BLOCKED_ON_PREREQUISITE`).

**Current verified state (read-only `gcloud` discovery, this session):**
exactly one GCP organization is visible to the operating credentials —
`ms-alkhaja-org`, organization ID `1090730370932` — serving as Domain A's
root. No second or third organization/Cloud Identity account exists. This
document exists to close that gap through human action; it performs none
of it.

---

## Part 1 — Independence Acceptance Criteria (Phase 2)

For both Domain B and Domain C, every criterion below is classified so governance and engineering never confuse "what the ADR requires" with "what this task recommends":

| # | Criterion | Domain B | Domain C | Classification |
|---|---|---|---|---|
| 1 | Separate Cloud Identity/Workspace administrative root from Domain A | Required | Required (also from B) | **MANDATORY_ARCHITECTURE_REQUIREMENT** (ADR-045 §4, ADR-044 §15A) |
| 2 | Separate GCP Organization attached to that root | Required | Required | **MANDATORY_ARCHITECTURE_REQUIREMENT** — a GCP Organization is automatically, 1:1 bound to its Cloud Identity/Workspace account (independently reconfirmed against current Google Resource Manager documentation this session); satisfying #1 satisfies this automatically, it is not a separate creation step |
| 3 | Distinct Super Admin population | Required | Required | **MANDATORY_ARCHITECTURE_REQUIREMENT** (ADR-045 §4's own reasoning: a shared Super Admin retains org-policy/IAM-Deny reach regardless of resource separation) |
| 4 | No standing Domain A administrator membership in B/C | Required | Required (also not B) | **MANDATORY_ARCHITECTURE_REQUIREMENT** (Gate A Decision 2) |
| 5 | No shared administrative group capable of controlling both roots | Required | Required | **MANDATORY_ARCHITECTURE_REQUIREMENT** (direct consequence of #3/#4 — a shared group is a shared population by another name) |
| 6 | No inherited IAM path from Domain A | Required | Required | **MANDATORY_ARCHITECTURE_REQUIREMENT** (ADR-044 §14 row G; verified, not assumed, per Part 6 below) |
| 7 | No shared break-glass credential | Required | Required | **APPROVED_GOVERNANCE_REQUIREMENT** (Gate A Decision 5 — ADR-045 §5 requires break-glass be independently governed; this task's own Gate A approval operationalizes that into "no shared credential," which the ADR text does not spell out in this exact form) |
| 8 | Independent recovery ownership (recovery email/phone/codes) | Required | Required | **RECOMMENDED_HARDENING** — not independently mandated by ADR-045 §4's literal text, but necessary in practice for #3/#4 to hold under a real account-recovery incident (already flagged this way in the Gate A decision package, G3) |
| 9 | Independent MFA/credential ownership, where technically practical | Required | Required | **RECOMMENDED_HARDENING** — same reasoning as #8 |
| 10 | Ability to create and govern the future signing/ledger project without Domain A administration | Required | Required | **MANDATORY_ARCHITECTURE_REQUIREMENT** — this is simply the operational restatement of #1–#6 holding in practice |

**Domain C must demonstrate the equivalent of every row above against BOTH Domain A and Domain B** — per Gate A Decision 3, approved as the strongest realization (a third independent domain), not merely the ADR's own weaker permitted floor. Nothing here silently elevates a recommendation to an ADR requirement: rows 8–9 remain explicitly marked as hardening, not architecture law, exactly as the existing Gate A package already stated.

**A provider-guidance caveat, disclosed honestly rather than omitted:** current Google Cloud architecture guidance (`docs/architecture/identity/best-practices-for-planning`, independently fetched this session) generally *discourages* splitting a single company into multiple Google Workspace/Cloud Identity accounts for departmental isolation, and specifically warns that "Google Workspace super admins have the ability to use domain-wide delegation to impersonate any user" — meaning a naively-configured second Workspace account does not automatically close every cross-account reach path. This does not contradict or weaken Gate A Decision 1 (which targets a different, security-driven threat model than Google's UX/administrative-overhead guidance), but it does add one concrete, additional adversarial check: **confirm no domain-wide delegation grant exists from Domain A's Workspace into any Domain B/C resource** — folded into Part 6's verification procedure below.

---

## Part 2 — Domain Identity Requirements (Phase 3)

### DOMAIN B — Signing: what the business owner must provide

| Field | What is needed | Placeholder |
|---|---|---|
| Intended Cloud Identity/Workspace domain | A domain the business owner controls DNS for — either a brand-new, disjoint domain (Google's own best-practice guidance, fetched this session, recommends this over a subdomain), or a dedicated subdomain of an existing domain the owner controls, used ONLY for this purpose | `<DOMAIN_B_DOMAIN>` |
| Proof/control of DNS domain | Ability to add a TXT or CNAME record for domain verification (exact record type/value is generated by Google during setup, per current Google documentation, and cannot be predicted in advance) | N/A — verified live during setup |
| Legal/business owner | The named individual or entity with authority to create a new Cloud Identity/Workspace account and accept its terms | `<DOMAIN_B_BUSINESS_OWNER>` |
| Primary Super Admin | A person who is NOT a Domain A Super Admin or standing administrator | `<DOMAIN_B_PRIMARY_SUPER_ADMIN>` |
| Secondary/recovery Super Admin | A second, independent person, also not overlapping with Domain A | `<DOMAIN_B_SECONDARY_SUPER_ADMIN>` |
| Independent recovery email/channel | A recovery contact not shared with any Domain A administrator's own recovery channel | `<DOMAIN_B_RECOVERY_CHANNEL>` |
| MFA ownership | Confirmation that Domain B's admins will enroll separate MFA devices/credentials, not shared with Domain A | `<DOMAIN_B_MFA_OWNER_ATTESTATION>` |
| Billing owner | Named individual/team responsible for Domain B's billing account decision (Part 5 below) | `<DOMAIN_B_BILLING_OWNER>` |
| Security reviewer | Named individual who will independently execute Part 6's verification (may overlap with Domain A's or be a dedicated third party — see Part 3's overlap rules) | `<DOMAIN_B_SECURITY_REVIEWER>` |
| Break-glass approvers | At least two named individuals, neither the requester, per Gate A Decision 5 | `<DOMAIN_B_BREAK_GLASS_APPROVER_1>`, `<DOMAIN_B_BREAK_GLASS_APPROVER_2>` |

### DOMAIN C — Compromise Ledger: what the business owner must provide

Identical field set, independently populated — **not derived from or shared with Domain B's answers**, since Domain C must be independent of both A and B:

| Field | Placeholder |
|---|---|
| Intended Cloud Identity/Workspace domain | `<DOMAIN_C_DOMAIN>` |
| Legal/business owner | `<DOMAIN_C_BUSINESS_OWNER>` |
| Primary Super Admin | `<DOMAIN_C_PRIMARY_SUPER_ADMIN>` |
| Secondary/recovery Super Admin | `<DOMAIN_C_SECONDARY_SUPER_ADMIN>` |
| Independent recovery email/channel | `<DOMAIN_C_RECOVERY_CHANNEL>` |
| MFA ownership | `<DOMAIN_C_MFA_OWNER_ATTESTATION>` |
| Billing owner | `<DOMAIN_C_BILLING_OWNER>` |
| Security reviewer | `<DOMAIN_C_SECURITY_REVIEWER>` |
| Break-glass/ledger-write approvers | `<DOMAIN_C_LEDGER_APPROVER_1>`, `<DOMAIN_C_LEDGER_APPROVER_2>` |

No name, email, domain, or organization is invented anywhere in this document — every value above is an explicit placeholder for human input.

---

## Part 3 — Administrator Non-Overlap Attestation Template (Phase 4)

Governance completes this table once the roots exist (populate with role titles or anonymized identifiers, never raw personal data in this repository):

```
DOMAIN A administrators (standing):  <LIST>
DOMAIN B administrators (standing):  <LIST>
DOMAIN C administrators (standing):  <LIST>

Attested:
  A ∩ B = ∅   [ ] CONFIRMED   [ ] EXCEPTION RECORDED BELOW
  A ∩ C = ∅   [ ] CONFIRMED   [ ] EXCEPTION RECORDED BELOW
  B ∩ C = ∅   [ ] CONFIRMED   [ ] EXCEPTION RECORDED BELOW
```

Separately (not required to be disjoint unless marked so):

| Population | Overlap rule | Classification |
|---|---|---|
| Standing administrators (A, B, C) | Must be pairwise disjoint | **PROHIBITED** to overlap |
| Super Admin populations (A, B, C) | Must be pairwise disjoint | **PROHIBITED** to overlap (this is the literal content of acceptance criterion #3) |
| Break-glass approvers | Must not include any standing administrator of the domain they approve into; MAY overlap across domains only if the individual holds no standing access in either | **PERMITTED_WITH_RISK_ACCEPTANCE** if the same person approves break-glass for two domains without standing access to either — record explicitly if chosen, since it does concentrate approval authority |
| Billing administrators | May overlap across domains — billing has no IAM reach into linked projects (independently reconfirmed, ADR-044 §17 item 8 discussion) | **PERMITTED** |
| Security reviewers | May overlap across domains — a single independent reviewer auditing all three domains is often preferable for consistency, provided they hold no standing administrative access anywhere | **PERMITTED** |
| Recovery-account owners | Should not overlap between domains' Super Admins (criterion #8, hardening) but MAY be a shared institutional process (e.g., a company's general executive escalation path) without violating the architecture requirement | **PERMITTED_WITH_RISK_ACCEPTANCE** if the shared process could plausibly reach account recovery for more than one domain in practice |

The architecture does **not** require billing or security-review populations to be disjoint — this template exists specifically so governance does not over-apply Decision 2's separation rule where it was never intended to reach.

---

## Part 4 — Cloud Identity / Workspace Creation Runbook (Phase 5)

**Independently verified this session against current official Google documentation** (`docs.cloud.google.com/resource-manager/docs/creating-managing-organization`, `docs.cloud.google.com/identity/docs/set-up-cloud-identity-admin`, `docs.cloud.google.com/architecture/identity/best-practices-for-planning`) — not asserted from training-data recollection alone. **Nothing below is executed by this task.**

| # | Step | Action type | gcloud-verifiable after? | Human attestation required? |
|---|---|---|---|---|
| 1 | Decide the domain/subdomain for the new root (disjoint domain recommended by Google's own guidance over a subdomain of an existing one) | Business decision | No | Yes — record the chosen domain |
| 2 | Create the Cloud Identity account (free tier is sufficient — no email/collaboration features are needed for a pure administrative root) via `workspace.google.com/gcpidentity/signup?sku=identitybasic`, or a full Google Workspace subscription if the business prefers | **Browser/admin-console only** — current documentation describes no API/gcloud path for account creation itself | No (account existence isn't a GCP-API-visible object until an org is created) | Yes |
| 3 | Verify domain ownership via the DNS TXT/CNAME record Google generates during setup | **Browser/admin-console only**, DNS-provider action | No | Yes — retain proof of the DNS record added |
| 4 | Establish the first (primary) Super Admin during account creation | **Browser/admin-console only** | Partially — `gcloud organizations describe` will not show Workspace admin roles directly; Workspace Admin Console access is required to confirm | Yes |
| 5 | Add a secondary Super Admin and configure independent recovery mechanisms (recovery email/phone, recovery codes) | **Browser/admin-console only** (Workspace Admin Console) | No | Yes |
| 6 | GCP Organization resource creation | **Automatic** — per current documentation, the org resource is created automatically once the Cloud Identity/Workspace account exists and the owner logs into Cloud Console and accepts terms (new accounts) or creates a project/billing account (existing accounts); there is no separate manual organization-creation step | **Yes** — `gcloud organizations list` (or `organizations.search()`) | No further action beyond step 2 |
| 7 | Verify the Organization's Cloud Identity/customer-ID relationship | Confirm the new organization's `directoryCustomerId` is distinct from Domain A's | **Yes** — `gcloud organizations describe <org-id> --format="value(directoryCustomerId)"` | No |
| 8 | Configure initial organization governance (IAM Admin role assignment, org policies) | Console, gcloud, or API — this step DOES have a gcloud/API path, unlike account creation itself | **Yes** — `gcloud organizations get-iam-policy <org-id>` | Yes — confirm only SIGNING_ADMIN_GROUP (or LEDGER_ADMIN_GROUP) receives Organization Administrator, never anyone from Domain A |
| 9 | Establish the billing relationship (Part 5 below) — separate account, not linked to Domain A's | Console/gcloud | Yes — `gcloud billing accounts list` | Yes — record the billing decision |
| 10 | Prepare for independent security review (Part 6) — no action here beyond scheduling; the review itself happens after project/resource creation, which remains `BLOCKED_ON_PREREQUISITE` until this runbook's steps 1–9 complete | N/A | N/A | Yes — schedule with SECURITY_REVIEWER |

**This task makes no claim of a gcloud/API automation for steps 1–5 that does not exist** — current documentation is explicit that Cloud Identity/Workspace account creation, domain verification, and Super Admin/recovery setup are browser-console-only actions. Steps 6–9 do have gcloud/API paths once the prerequisite account exists.

**A note on domain choice**, directly from Google's own architecture guidance: prefer a genuinely disjoint domain over a subdomain of Domain A's existing domain — the guidance explicitly warns against subdomain relationships between separately-governed accounts. If a disjoint domain is impractical, a dedicated subdomain is technically possible (domain verification can be scoped to a subdomain), but should be treated as a disclosed, weaker choice, not the default.

---

## Part 5 — Billing Decision Template (Phase 8)

Carrying forward the already-approved rule (Gate A Decision 4; `RECOVERY_AUTHORITY_PLACEMENT_AND_BILLING_GOVERNANCE_DECISION.md` §5.2) without re-deciding it:

- **Separate billing account per domain is the recommended default.** This is an availability/blast-radius control, never a claim of IAM or cryptographic independence — a Billing Account Administrator has no IAM/KMS/storage reach into a linked project, independently reconfirmed against current Google Cloud Billing documentation.
- **This document does not select a billing account for any domain.**

**If governance instead chooses shared billing for Domain B or C**, the following record must be produced and signed before that choice takes effect:

```
SHARED BILLING RISK ACCEPTANCE RECORD

Domain(s) affected:            <B and/or C>
Billing account to be shared:  <ACCOUNT_ID_OR_NAME>
Shared with which environment(s): <e.g., emg-platform-staging, Domain A prod, etc.>
Accepted risk (verbatim, do not weaken):
  "A billing-account-level action (suspension, non-payment, fraud hold,
   or an administrative mistake) affecting the shared account can disable
   read/write access to this domain's resources for the duration of the
   billing-disabled window, independent of and without affecting
   cryptographic integrity, Bucket Lock enforcement, or object/key
   survival — all of which are empirically confirmed to survive a
   billing-disabled window unchanged."
Accepted by (named role, not this document): <RELEASE_APPROVER or equivalent>
Date: <DATE>
```

---

## Part 6 — Root Verification Procedure (Phase 6) — to be run by engineering AFTER humans complete Part 4

All read-only `gcloud`/API calls. Produces:

| Field | How obtained | Verifiable via API? |
|---|---|---|
| `DOMAIN_A_ORG_ID` | `gcloud organizations list` (already known: `1090730370932`) | Yes |
| `DOMAIN_B_ORG_ID` | `gcloud organizations list` after Domain B's root exists | Yes |
| `DOMAIN_C_ORG_ID` | Same, for Domain C | Yes |
| `DOMAIN_A_CUSTOMER_ID` | `gcloud organizations describe 1090730370932 --format="value(directoryCustomerId)"` | Yes |
| `DOMAIN_B_CUSTOMER_ID` | Same pattern once the org exists | Yes |
| `DOMAIN_C_CUSTOMER_ID` | Same pattern once the org exists | Yes |
| Organizations are distinct | Compare all three org IDs and all three `directoryCustomerId` values — must be pairwise different | **Automatable** |
| No relevant ancestor relationship | `gcloud organizations describe` has no `parent` field for a top-level organization — organizations are never nested under each other in GCP's resource hierarchy, so this is structurally guaranteed once each is confirmed to be its own top-level org, not merely asserted | **Automatable** |
| No broad cross-domain IAM grant | `gcloud organizations get-iam-policy <org-id>` for each org; confirm no principal from another domain's admin group appears | **Automatable**, but interpreting "is this principal really from another domain" requires the Part 3 attestation as ground truth — **partially MANUAL_EVIDENCE_REQUIRED** |
| No TokenCreator/actAs bridge | `gcloud iam service-accounts get-iam-policy` across all Domain B/C service accounts; confirm no Domain A principal holds `roles/iam.serviceAccountTokenCreator` or equivalent | **Automatable** |
| No shared service-account key mechanism | Confirm no service-account key (as opposed to WIF) exists at all for `recovery-signer`/`recovery-authority` (this codebase's own design already forbids static keys; verify no exception was introduced during provisioning) | **Automatable** (`gcloud iam service-accounts keys list` should show only system-managed keys, none user-managed) |
| No shared runtime identity | Confirm `recovery-authority-runtime`, `recovery-signer`, and the ledger-writer principal are three distinct GSAs in three distinct projects/domains | **Automatable** |
| No obvious cross-domain IAM binding | Full policy diff against `iam/manifest.json`'s `forbidden_permissions` sets, run against the real exported policies | **Automatable** |
| No domain-wide delegation bridge (Part 1's provider-guidance caveat) | Confirm no domain-wide delegation grant in Domain A's Workspace Admin Console names any Domain B/C service account or API scope | **NOT gcloud-verifiable — requires Workspace Admin Console access; MANUAL_EVIDENCE_REQUIRED** |

**Everything still requiring human evidence because Google APIs cannot prove it:** Super Admin population membership and its non-overlap (Workspace Admin Console, not a GCP API); recovery-channel/MFA independence (same); domain-wide delegation absence (same); the good-faith accuracy of the Part 3 attestation itself (no API can prove who *actually* controls a credential versus who is merely listed).

---

## Part 7 — IAM Self-Falsification Plan (Phase 7) — **PLAN ONLY, not executed in this task**

| Attempt | Target capability | Expected denial | Enforcement layer | Evidence to capture |
|---|---|---|---|---|
| AUTHORITY_ADMIN → Domain B: IAM policy mutation | `setIamPolicy` on a Domain B resource | Denied — no cross-org IAM path exists by construction | GCP IAM (org boundary) | `gcloud` error response, timestamp |
| AUTHORITY_ADMIN → Domain B: KMS administration/signing | `cloudkms.cryptoKeyVersions.useToSign` / key admin on Domain B's key | Denied | GCP IAM | Error response |
| AUTHORITY_ADMIN → Domain C: ledger mutation | Attempt to write/edit a ledger entry | Denied | GCP IAM + `compromiseledger.Ledger`'s own no-mutation-method interface (S3-qualified, defense in depth) | Error response + confirm no mutation method exists in the interface at all |
| SIGNING_ADMIN → Domain A: Spanner administration/data mutation | `spanner.databases.updateDdl` or data write on Domain A's database | Denied | GCP IAM (org boundary) | Error response |
| SIGNING_ADMIN → Domain A: witness bucket administration | `storage.buckets.update` / retention change on Domain A's bucket | Denied | GCP IAM | Error response |
| SIGNING_ADMIN → Domain C: pin-store-equivalent or ledger administration | Any Domain C administrative action | Denied | GCP IAM | Error response |
| LEDGER_ADMIN → Domain A: IAM policy mutation | `setIamPolicy` on Domain A | Denied | GCP IAM | Error response |
| LEDGER_ADMIN → Domain B: pin-store administration | `storage.buckets.update` on Domain B's pin-store bucket | Denied | GCP IAM | Error response |
| Any domain → any other: service-account impersonation | `iam.serviceAccounts.getAccessToken`/`.actAs` cross-domain | Denied | GCP IAM | Error response |
| Any domain → any other: domain-wide delegation reach | Attempt to use a Workspace domain-wide-delegation grant to reach another domain's API scope | Denied (should be, once Part 6's check confirms none exists) | Workspace Admin Console policy | Console screenshot/export, not a `gcloud` artifact |

**No destructive or privilege-escalating test is authorized by this task.** This table is the design for Decision 6's audit to execute later, against real infrastructure, by SECURITY_REVIEWER — not something this task runs.

---

## Part 8 — Break-Glass Onboarding (Phase 9)

Translating the approved model (Gate A Decision 5) into what must exist before it can function:

| Requirement | Classification |
|---|---|
| Two independent approvers, requester excluded | **GOVERNANCE_ENFORCED** — no GCP feature enforces "requester cannot approve their own request"; this is a process control the approval workflow (ticketing/human process) must implement |
| Just-in-time binding | **AUTOMATION_ENFORCED** — achievable via a time-bound IAM Condition or an external JIT-access tool (e.g., a temporary binding created by an approved automation), not a manual standing grant |
| Incident-specific scope | **GOVERNANCE_ENFORCED** for *deciding* the scope; **AUTOMATION_ENFORCED** for *encoding* it narrowly once decided |
| Automatic expiry | **AUTOMATION_ENFORCED** — IAM Conditions support time-based expiry natively (`request.time < timestamp(...)`), independently verifiable via `gcloud` |
| 4-hour recommended maximum, fresh approval to extend | **GOVERNANCE_ENFORCED** (the duration choice and re-approval requirement); the expiry mechanism itself is AUTOMATION_ENFORCED |
| Complete audit trail | **PROVIDER_ENFORCED** — Cloud Audit Logs records every IAM policy change and every KMS operation automatically, without additional configuration for the base log; ensuring it's retained/exported to a tamper-resistant sink is **AUTOMATION_ENFORCED** |
| Post-event review | **GOVERNANCE_ENFORCED** — no technical control performs this |
| No standing cross-domain administration | **PROVIDER_ENFORCED** at the org-boundary level (once Part 6 confirms no cross-org grant exists) |

**Nothing above is misclassified as a technical control where it is actually a process one, or vice versa.** As of this document, the JIT/expiry automation itself is **NOT_YET_IMPLEMENTED** — no Terraform/script/tool exists anywhere in this repository to create or expire such a binding (consistent with S4's own finding that no executable IaC engine exists in this repository); implementing it is future, separately-scoped work, not claimed as already built.

---

## Part 9 — Human Action Pack (Phase 10)

*(This section is written for a non-engineering business owner. If any term here is unclear, contact engineering before acting — do not guess.)*

**WHAT MUST I CREATE?**
Two new, independent Google Cloud Identity (or Google Workspace) accounts — one for "Signing" (Domain B), one for "Compromise Ledger" (Domain C). Each needs its own domain (a brand-new domain is preferred; see Part 4, step 1).

**WHO MUST BE DIFFERENT?**
The people who administer these two new accounts must NOT be the same people who administer your existing EMG Google Cloud organization (`ms-alkhaja-org`), and must not be the same as each other either. Each needs at least two people (a primary and a backup admin).

**WHAT INFORMATION MUST I GIVE ENGINEERING?**
Fill out Part 11's return package below — domain names, organization IDs (engineering can look these up once you tell them the domain), and written confirmation ("attestation") that the people involved don't overlap with your existing team. See Part 11 for the exact list.

**WHAT MUST I NOT DO?**
- Do not reuse an existing project inside your current Google Cloud organization and call it "independent" — it is not.
- Do not create a subdomain of your existing domain unless a genuinely new domain is impractical (Part 4 explains why).
- Do not send engineering any password, MFA code, recovery code, private key, or service-account key file — see Part 11.
- Do not lock any storage retention policy or create any signing key yet — that happens later, in a separate step, only after engineering verifies everything below.

**WHAT EVIDENCE MUST I SAVE?**
A record (screenshot or written note is fine) of: the domain you registered, the date each account was created, who the primary and backup admins are, and confirmation that their recovery email/phone and MFA devices are not shared with your existing team.

**WHEN DO I RETURN TO CLAUDE / ENGINEERING?**
Once both new accounts exist, their domains are verified, and their admins are set up — bring back exactly the items listed in Part 11. Engineering will then independently verify everything (Part 6) before anything further happens.

---

## Part 10 — Return-to-Engineering Package (Phase 11)

```
DOMAIN_B_PRIMARY_DOMAIN:                 <value>
DOMAIN_B_ORGANIZATION_ID:                <value>              (engineering can also look this up once given the domain)
DOMAIN_B_CLOUD_IDENTITY_CUSTOMER_ID:     <value, if available>
DOMAIN_B_SUPER_ADMIN_ATTESTATION:        <"confirmed non-overlapping with Domain A, 2 admins named">
DOMAIN_B_BILLING_DECISION:               <"separate account" or "shared — risk acceptance record attached">

DOMAIN_C_PRIMARY_DOMAIN:                 <value>
DOMAIN_C_ORGANIZATION_ID:                <value>
DOMAIN_C_CLOUD_IDENTITY_CUSTOMER_ID:     <value, if available>
DOMAIN_C_ADMIN_ATTESTATION:              <"confirmed non-overlapping with Domain A and Domain B, 2 admins named">
DOMAIN_C_BILLING_DECISION:               <"separate account" or "shared — risk acceptance record attached">

ADMIN_NON_OVERLAP_ATTESTATION:           <Part 3's completed template>
BREAK_GLASS_APPROVER_ATTESTATION:        <names/roles of the 2+ approvers per domain, confirmed independent>
```

**This task, and the return package it defines, will NEVER request:** passwords, MFA secrets/seed codes, recovery codes, private keys, service-account key files, OAuth tokens, or any other credential material. If anything ever appears to ask for one of these, treat it as a red flag, not a legitimate step in this process.

---

## Cross-references

- `RECOVERY_AUTHORITY_ADMINISTRATIVE_INDEPENDENCE_DECISION_PACKAGE.md` — Gate A governance decision (APPROVED) this runbook operationalizes.
- `RECOVERY_AUTHORITY_PRODUCTION_PROVISIONING_PLAN.md` — the resource plan; Domain B/C rows remain `BLOCKED_ON_PREREQUISITE` until this runbook's Part 4 is completed and Part 6 passes.
- `docs/architecture/EMG_ADR-044_*` §14 row G, §15, §15A, §17 item 9.
- `docs/architecture/EMG_ADR-045_*` §4, §5, §7.
- `internal/authority/iam/manifest.json` and README — the principal definitions Part 6/7's checks are run against.
- `internal/authority/provisioning/contract.json` and README — the declarative resource/ordering contract this runbook's Domain B/C entries unblock.

## What this document does not do

- Does not create any GCP project, organization, Cloud Identity/Workspace account, billing account, IAM binding, Kubernetes object, or production resource.
- Does not collect, request, or store any credential material.
- Does not amend ADR-044 or ADR-045, or silently downgrade Gate A Decision 3's approved third-domain model for Domain C.
- Does not mark any root as created or verified — Part 6 remains to be executed once, and only once, humans complete Part 4.
- Does not authorize production provisioning, Gate B, or Gate C.
