# Recovery Authority production placement and administrative boundary decision

**Document type:** L4 delegated governance decision; not an ADR

**Owner:** Recovery Authority governance owner

**Approval authority:** Project Architect and Security owner

**Governing authority:** ADR-044 and ADR-045

**Status:** Proposed for explicit production-placement approval

`BLOCKER_A_STATUS = EXPERIMENTALLY_PASSED`

`ADR-044 = Accepted`

`ADR-045 = Accepted`

`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED`

## 1. Decision scope and authority

This record selects operational placement and administrative boundaries within the
architecture already fixed by ADR-044 and ADR-045. It creates no protocol, product, or
architecture change and does not amend either ADR. Under GR-001 it remains L4 and may
only operationalize those accepted decisions.

Approval of this placement record is one future provisioning gate. Repository presence
alone is not approval, and even its approval would not authorize deployment or close
S3–S7.

## 2. Placement decisions

### A. Spanner and GCS authority domain

Spanner is the sole transition authority and GCS is the passive immutable witness, as
defined by ADR-044. They are administered within the authority/witness governance
domain but have distinct runtime permissions and responsibilities. Spanner authority
administrators cannot mutate witness records through their authority role, and witness
administrators cannot mutate Spanner through their witness role.

This domain has no administrative reach into the signing trust domain.

### B. Signing trust domain

ADR-045 Option A is mandatory: production signing uses an independently administered
GCP-native signing project/domain outside the IAM hierarchy and administrative reach
of the Spanner/GCS domain, with distinct, non-overlapping human administrative control.

- Authority/witness administrators cannot grant themselves signing capability,
  administer signing IAM, replace signer workloads, or control signing-key lifecycle.
- Signing-domain administrators cannot mutate Spanner or GCS, administer witness
  retention/liens/billing, or become Recovery Authority runtime operators through
  inherited authority.
- Exact resource topology must be qualified against actual IAM inheritance and any
  cross-boundary organization, identity, and billing reach before provisioning.

### C. Witness project

The production GCS witness must be in a project separate from the Spanner authority
project. The witness project retains independently governed retention, lien, project,
and billing controls. Separation of projects does not by itself prove administrative
independence; effective IAM reach must also be reviewed.

### D. Organization boundary

Same-organization witness placement may retain residual organization-administrator
risk. The real-GCP Bucket Lock trials qualified observed retention, lien, deletion,
restore, and billing behavior; they did not eliminate organization-admin governance
risk or qualify any production organization topology.

For signing, ADR-045's stronger requirement controls: the signing project/domain must
have no shared organization, folder, parent-resource inheritance, or other effective
administrative path by which authority/witness administrators could grant themselves
signing power. A same-organization construction alone is not sufficient.

### E. Billing account

The committed real-GCP qualification trials used a billing account also associated
with staging. This did not invalidate the observed Bucket Lock integrity evidence. It
did reveal billing as an availability and correlated-control dependency: after project
restore, the trial required an authorized billing relink before object access resumed.

The production default is a billing account operationally separated from staging and
non-production where practical. Separate billing is an availability and governance
control, not a cryptographic requirement. Shared billing requires explicit documented
risk acceptance under Section 4 before provisioning.

### F. Billing recovery ownership

Only a designated Billing Relinker may relink the exact approved Recovery Authority
project to its exact pre-approved account after project restoration. This principal is
not an ordinary runtime identity, holds no signing capability, cannot alter unrelated
billing configuration as part of recovery, and produces an audit record for every use.

### G. Lien modifier

Lien modification is a rare break-glass capability, never a runtime capability. The
Lien Modifier is separately controlled, is not a witness writer, and cannot sign. Every
use requires dual approval, exact scope, temporary elevation, and audit evidence.

### H. Runtime principal

No Recovery Authority runtime principal may hold project-deletion, lien-modification,
retention-administration, billing-relink, signing-administration, organization-
administration, or general project-administration capability. Runtime grants are
resource-specific and limited to the accepted protocol operation they perform.

## 3. Administrative boundary requirements

The following combinations are prohibited because they collapse an accepted boundary:

- Billing Relinker with Recovery Authority runtime authority or signing capability;
- Lien Modifier with witness-writer or runtime capability;
- signing administrator with Spanner/GCS administration;
- authority/witness administrator with any path to grant or invoke signing;
- runtime principal with destructive, retention, billing, lien, key-administration, or
  organization-administration rights; and
- a single human approval path controlling both sides of a break-glass boundary.

Administrative separation is evaluated by effective capability, including inherited
IAM, impersonation, group membership, workload replacement, policy administration,
and credential recovery—not by project labels alone.

## 4. Risk acceptance table

| Control | Recommended default | Alternative | Residual risk | Alternative approver |
|---|---|---|---|---|
| Witness project placement | Separate project from Spanner authority | None for production | Co-location collapses project administration and incident containment | No exception under this decision; architecture review required |
| Witness billing | Billing account operationally separate from staging/non-production | Shared account | Correlated suspension, quota, administration, and recovery-access outage | Project Architect, Security owner, and Billing owner |
| Signing administrative domain | ADR-045 Option A independent domain with non-overlapping administrators | External independently reviewed signing service only through a future decision | Any reachable shared administrator can mint or redirect signing authority | No same-domain exception; architecture review required |
| Same-organization witness | Prefer administratively separated placement with explicit org-risk controls | Same organization after effective-access review | Organization administrator may retain correlated control over project/IAM governance | Project Architect and Security owner |
| Shared billing with staging | Separate production billing | Shared billing with documented controls | Staging and production availability/recovery become correlated | Project Architect, Security owner, and Billing owner |
| Break-glass access | Two independent approvers, exact scope, temporary grant, full audit | No standing broad access alternative | Misuse can affect project, lien, billing, or key lifecycle despite runtime separation | Security owner plus one independent domain owner |

Risk acceptance never authorizes a protocol bypass, signing-domain collapse, witness
co-location with Spanner, or runtime possession of prohibited capabilities.

## 5. Production provisioning gate

No production Recovery Authority project may be provisioned until all are recorded as
complete:

1. S3 signing trust-domain realization and provider qualification;
2. S4 IAM manifests and effective-access review;
3. explicit approval of this S9 placement decision;
4. named, approved production billing owner and Billing Relinker;
5. named, approved lien owner and break-glass approvers; and
6. approval of the standalone production recovery runbook.

Provisioning remains blocked if any approved project, organization, billing, signing
lineage, administrator set, impersonation path, or separation claim is unknown.

## 6. Evidence and review requirements

Before approval, preserve a redacted placement record containing exact production
resource identities, effective IAM and inheritance analysis, administrator and approver
sets, billing ownership, lien ownership, signing-domain independence evidence, and
accepted exceptions. Do not place credentials, private keys, tokens, personal email
addresses, or reusable commands containing sensitive identifiers in this document.

Re-review this decision after any organization move, billing-account change, IAM
inheritance change, signing-domain change, witness-project replacement, break-glass
model change, or compromise affecting an administrative domain.

## 7. Security assertions

This decision fails closed against the required placement attacks:

- a Billing Relinker with runtime authority violates Sections 2F and 3;
- a Lien Modifier who is also a witness writer violates Sections 2G and 3;
- a signing administrator with GCS/Spanner administration violates ADR-045 and
  Sections 2B and 3;
- an authority administrator able to grant signing rights violates the same boundary;
- same-project witness placement violates Section 2C; and
- shared production/staging billing without explicit approval violates Sections 2E
  and 4.

These controls complement the runbook's protocol checks; they never replace content
binding, key authorization, acceptance provenance, or compromise-ledger verification.

## 8. Approval boundary

This document is ready for independent governance review, not self-approved by its
creation. Until the named approval authorities approve the exact production placement
and every Section 5 gate is complete:

`PRODUCTION_APPROVAL_STATUS = NOT ESTABLISHED`.
