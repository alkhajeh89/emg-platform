# Recovery Authority — Production IAM Design (ADR-044/ADR-045 S4)

This package is the S4 deliverable: the production GCP IAM principal design
required to enforce ADR-044 §15's runtime separation and ADR-045 §4/§5's
signing administrative independence, concretized against the actual APIs
S1–S3 landed. **It creates, modifies, binds, enables, disables, or
provisions no real GCP resource or IAM policy.** `manifest.json` is data;
`manifest.go` parses and validates it entirely offline; the `_test.go`
files prove structural security properties against that data. Actually
provisioning real principals from this design is S6 (governed
bootstrap/provisioning, ADR-044 §17 item 5) — not begun here.

## Why this is JSON, not Terraform

No Terraform, Pulumi, Deployment Manager, or other GCP-executable IaC tool
exists anywhere in this repository (verified: zero `.tf` files, no
`infra/` module referencing a cloud provider). This repository's one
established precedent for declaring an infrastructure-adjacent identity
inventory as code is `infra/provisioning/projector-identities.schema.json`
+ `.example.json` (Identity/Audit, ADR-041 §6): a versioned JSON Schema,
a validated instance, and a same-language loader/test pair, with the
repository owning the schema and an environment owning the values. This
package follows that same shape — `manifest.schema.json` +
`manifest.json` + a Go loader/validator — because Recovery Authority's
IAM design is self-contained to one Go service module and Go's `embed`
requires the data to live inside the module's own directory tree.

**Recommendation for the eventual S6 implementation**: when governed
bootstrap/provisioning is authorized, the natural execution form is
Terraform `google_kms_crypto_key_iam_member` / `google_spanner_database_iam_member`
/ `google_storage_bucket_iam_member` resources (or an equivalent
declarative GCP IAM tool), generated or cross-checked from this same
`manifest.json` rather than hand-duplicated — so the reviewed design and
the applied policy never drift apart. This package does not implement
that generation step; S6 does.

## Principals (Phase 1)

Six principals, one per `manifest.json` entry, none collapsed for
convenience:

| ID | Domain | Kind | Grounding |
|---|---|---|---|
| `recovery-authority-runtime` | `authority_witness` | runtime | `spannercommit.Client.Commit`, `gcswitness.Adapter.{CreateExactIfAbsent,ReadExact,Exists}` |
| `recovery-signing` | `signing` | runtime | `kmssigner.Signer.SignCommittedDigest` |
| `recovery-pin-capture` | `signing` | administrative | `keypinning.CaptureFromKMS` |
| `compromise-ledger-writer` | `compromise_ledger` | administrative | not yet implemented (boundary only) |
| `recovery-verification-read` | `authority_witness` | runtime | S8 runbook §5/§11 (no dedicated Go entry point yet) |
| `recovery-bootstrap-deployment` | `bootstrap` | administrative | exclusion boundary only — S6 |

Every field required by Phase 1 (purpose, required/forbidden permissions,
resource scope, trust domain, runtime-vs-administrative, credential
model, rotation responsibility) is in `manifest.json`; see that file for
the exact text and citations.

## Permission derivation (Phase 2) — two findings from independent verification

Both independently re-verified against current official Google Cloud
documentation before being encoded here, not assumed from prior
recollection:

1. **`roles/spanner.databaseUser` bundles `spanner.databases.updateDdl`
   and `spanner.databases.getDdl`** alongside its data-plane permissions.
   Granting it to `recovery-authority-runtime` would give the runtime
   schema-mutation capability ADR-044 §15 reserves for a separate
   bootstrap/administrative role. `manifest.json` therefore lists an
   exact custom-role permission set (session lifecycle, read-write/
   read-only transaction begin, read/select/write, `databases.get`,
   `instances.get`) and explicitly forbids `updateDdl`/`getDdl`/
   `changequorum`/`adapt`/`databaseOperations.*`.
2. **Cloud KMS IAM policies cannot be bound at the `CryptoKeyVersion`
   level** — only at `CryptoKey` or above. ADR-045 §7B's "where the
   provider's IAM model permits version-level granularity" is therefore
   never satisfied for this provider; binding is necessarily at the
   `CryptoKey` level, and the restriction to exactly one active
   `CryptoKeyVersion` is enforced entirely by `kmssigner.Signer`'s own
   fixed, single-version, construction-time configuration (verified by
   `kmssigner`'s own tests) — never by IAM. This is recorded as fact, not
   claimed as an IAM-enforced property.

`roles/cloudkms.signer` and `roles/cloudkms.publicKeyViewer` were also
independently checked and found to bundle `cloudkms.locations.{get,list}`
and `resourcemanager.projects.get` beyond their core permission — harmless
read-only extras, but `manifest.json` uses exact single-permission custom
roles instead, per Phase 2's preference for explicit permission lists over
convenient predefined roles.

`compromise-ledger-writer` and `recovery-verification-read` have **no
GCP permission grounded in landed code** today: `compromiseledger` and
`kmsverifier` make zero live cloud API calls (confirmed by direct source
inspection — `FileLedger`/`FileStore` are local-filesystem-backed,
explicitly documented in their own package comments as qualification-
grade, not production mechanisms). Their `required_permissions` are
therefore empty by evidence; only their exclusion boundary
(`forbidden_permissions`) against other domains is established now, per
Phase 2's "do not invent capabilities not required by code/ADR."

## Administrative independence (Phase 3)

For every runtime/administrative principal in `manifest.json`,
`forbidden_permissions` and the policy tests in `policy_test.go` jointly
prove **none** of the following appear in `required_permissions`:

| Capability | Present in any principal? |
|---|---|
| `*.setIamPolicy` / `*.getIamPolicy` (any resource type) | No (`TestPolicy10`) |
| `iam.serviceAccounts.getAccessToken` / `.actAs` (impersonation) | No (`TestPolicy12`) |
| `iam.serviceAccounts.signBlob` / `.signJwt` | No (`TestPolicy12`) |
| `iam.serviceAccountKeys.create` | No (`TestPolicy11`) |
| `iam.roles.update` (custom-role mutation) | No — explicit in `recovery-authority-runtime`'s forbidden list; absent from every principal's required list |
| `resourcemanager.*` (project/folder/org administration) | No (`TestPolicy13`) |
| `cloudkms.*` on any principal outside the signing domain | No — `recovery-authority-runtime` and `compromise-ledger-writer` hold zero `cloudkms.*` permissions (`TestPolicy04`, `TestPolicy08`) |
| `spanner.*` on any principal outside the authority/witness domain | No — `recovery-signing` and `recovery-pin-capture` hold zero `spanner.*` permissions (`TestPolicy02`) |
| Wildcard (`*`) or broad `owner`/`editor`/`admin` role | No (`TestPolicy15`) |

`TestAttackCD_CrossDomainResourceScopesUseDistinctProjectPlaceholders`
additionally proves the `signing` domain's resource-scope pattern and the
`authority_witness` domain's resource-scope pattern reference **different**
project placeholders (`{signing_project}` vs. `{authority_project}`) — the
design itself models them as separate resource hierarchies, not merely
separate permission lists within one project.

**What this proves, and what it does not.** These checks prove that
*this repository's own principal definitions* never request a
cross-domain or self-escalating permission. They do **not**, and cannot,
prove that a real deployment's actual GCP organization/folder/project
hierarchy grants no *inherited* broad role that overrides these narrow
bindings, and they do not prove the `{signing_project}` and
`{authority_project}` placeholders will resolve to genuinely
IAM-unreachable projects — ADR-045 §4 already states this precisely:
"GCP's exact IAM-inheritance semantics for whichever concrete resource
shape is chosen... must be independently verified against current,
authoritative GCP documentation and proven during implementation/
provisioning qualification" (S7+/staging qualification), and ADR-044 §15A
property 5 blocks production approval until that concrete trust boundary
is separately reviewed and qualified. **This manifest narrows the
boundary as far as repository-level IAM design can; it does not, and does
not claim to, close the organizational-governance gap ADR-044 §14 row G
and ADR-045 §4 already left explicitly open.**

## Attack matrix (Phase 6)

| # | Attack | Result | Where proven |
|---|---|---|---|
| A | Compromised signing runtime tries to mutate Spanner state | Fails — `recovery-signing` holds zero `spanner.*` permissions | `TestPolicy02_AttackA` |
| B | Compromised RA runtime tries to sign a forged payload | Fails — `recovery-authority-runtime` holds zero `cloudkms.*` permissions | `TestPolicy04_AttackB` |
| C | Signing-domain admin self-grants Spanner mutation | Structurally excluded from every defined principal (no `setIamPolicy` anywhere); domains use distinct resource-scope placeholders | `TestPolicy10`, `TestAttackCD` — **org-governance limit applies, see above** |
| D | Authority-domain admin self-grants KMS signing | Symmetric to C | `TestPolicy10`, `TestAttackCD` — **org-governance limit applies** |
| E | Pin-capture principal attempts `AsymmetricSign` | Fails — `recovery-pin-capture` explicitly forbids and never requires `useToSign` | `TestPolicy06_AttackE` |
| F | Signer attempts `GetPublicKey`/admin/disable/destroy/rotate | Fails — `recovery-signing` holds zero admin/view permissions | `TestPolicy07_AttackF` |
| G | Runtime principal attempts SA impersonation | Fails — no principal holds `getAccessToken`/`actAs`/`signBlob`/`signJwt` | `TestPolicy12_AttackG` |
| H | Runtime principal attempts SA key creation | Fails — no principal holds `iam.serviceAccountKeys.create` | `TestPolicy11_AttackH` |
| I | Runtime principal attempts IAM-policy mutation | Fails — no principal holds any `setIamPolicy`/`getIamPolicy` | `TestPolicy10_AttackI` |
| J | Compromise-ledger writer suppresses/replaces historical state | Defended at the **code** level, not IAM: `compromiseledger`'s `Ledger` interface has no `Delete`/`Update`/`Edit`/`Remove`/`Overwrite`/`Truncate` method anywhere (S3, `compromiseledger.TestCompromiseLedgerHasNoMutationMethod`); this package additionally forbids `storage.objects.update`/`.delete` for `compromise-ledger-writer` so a future provider-backed store cannot be granted in-place-mutation capability either | `TestPolicy08_AttackJ` + S3's existing test |
| K | A broad inherited project role (e.g. `roles/editor`) defeats a narrow resource binding | **Cannot be disproven by this manifest.** GCP IAM Allow policies are additive down the resource hierarchy (org→folder→project→resource); a broad role granted above any of these principals' resources would supply the same permissions regardless of how narrow this manifest's own bindings are. Only an IAM Deny policy (an organization-level construct) or strict absence of broad grants on the relevant projects can close this — that is S9/organizational governance, not a repository artifact. **Not modeled as passing; recorded as an open production-qualification requirement.** |
| L | A break-glass administrator crosses both domains | **Cannot be disproven by this manifest.** ADR-045 §4/§5 requires break-glass be independently governed and auditable, but a genuine organization-level super-admin sits above both domains by definition — closing this fully depends on the concrete, independently-administered signing trust domain realization ADR-045 §4 explicitly defers to a "separate, subsequent implementation-review decision" (§17 item 9) and ADR-044 §14 row G leaves open. **What this manifest does provide**: none of the *standing* principals defined here have cross-domain or self-escalating capability during normal operation — only an out-of-band, above-both-domains actor could cross them, which is the scope ADR-045 already scoped this risk to. |

K and L are listed as attacks this design does **not** claim to defeat,
per this task's explicit instruction not to claim impossible isolation.

## Machine-testable properties (Phase 5)

All 15 required properties plus the checkable attack-matrix entries are
Go tests in `policy_test.go`, run via ordinary `go test
./internal/authority/iam/...` — no separate tool invocation needed.
`manifest_test.go` covers structural well-formedness (unique IDs, valid
enums, no literal resource identifiers, no required/forbidden overlap).
`boundary_test.go` proves this package itself never imports a cloud SDK
or credential-handling capability, mirroring S1–S3's own AST-based
boundary-test convention.
