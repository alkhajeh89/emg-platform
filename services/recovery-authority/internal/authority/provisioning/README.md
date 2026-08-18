# Recovery Authority — Governed Provisioning Contract (ADR-044/ADR-045 S6 Phase 8)

This package is the S6 Phase 8 deliverable: a declarative, machine-checked
record of what must exist, be bound, be deployed, and be executed — and in
what order — before a Recovery Authority environment's first legitimate
genesis (`bootstrap.ExecuteGenesis`) can run. **It creates, applies, binds,
or provisions no real GCP resource, IAM policy, or Kubernetes object.**
`contract.json` is data; `contract.go` parses and validates it entirely
offline; the `_test.go` files prove structural properties against that
data, including cross-referencing every principal ID against
`iam/manifest.json` so the two documents cannot silently drift apart.

## Why this is JSON, not Terraform

S4 already established (`iam/README.md`) that no executable GCP IaC
framework exists anywhere in this repository — zero `.tf` files, no
`infra/` module referencing a cloud provider. S6 Phase 8's own
authorization is explicit: *"If a real executable IaC engine is now
genuinely required... STOP before introducing one. Report exactly why and
propose the smallest governance-consistent choice."*

That evaluation was made here, deliberately: this contract's job is to
**declare** the required resources, bindings, and ordering precisely enough
that a human operator (or a future, separately-reviewed automation) cannot
misread or reorder them — not to **apply** anything. A JSON contract plus a
Go validator does that completely; introducing Terraform (or any other
engine) would add the ability to *execute* against real GCP, which this
task does not authorize and which would itself need separate credential
plumbing, state-file management, and review. The smallest
governance-consistent choice is therefore the same shape `iam/manifest.json`
already established, extended rather than replaced.

If a later, explicitly authorized task does introduce real execution
(Terraform or otherwise), the natural implementation reads this contract's
`resource_requirements`, `principal_bindings`, and `execution_order` as its
input rather than re-deriving them by hand — so the reviewed design and the
applied infrastructure never drift apart.

## What this contract contains

- **`resource_requirements`**: every GCP resource that must exist *before*
  genesis can run (Spanner instance/database, GCS witness bucket with
  Bucket Lock retention, KMS key ring/CryptoKey/CryptoKeyVersion), each
  with a `{placeholder}`-only resource-name pattern (never a literal ID)
  and a `must_exist_before_genesis` flag.
- **`principal_bindings`**: how each `iam/manifest.json` principal maps to
  a Kubernetes ServiceAccount (from `infra/kubernetes/base/service-accounts.yaml`,
  S6 Phase 7) and a `{placeholder}`-form GCP service-account identity, plus
  whether the binding is a *standing* grant (`recovery-authority-runtime`,
  `recovery-signing`) or a *temporary, revoked-after-use* one
  (`recovery-bootstrap-deployment`, S6 Phase 2).
- **`deployment_manifests`**: pointers to the already-committed
  `infra/kubernetes/base/*.yaml` files (S6 Phase 7) — this contract never
  embeds manifest content, only references it, so there is exactly one
  copy of each manifest's truth.
- **`execution_order`**: the full bootstrap sequence as a dependency graph
  (`contract.go`'s `Validate` rejects unknown dependencies and dependency
  cycles; `OrderedSteps` returns a real topological order computed from
  `depends_on`, never trusted from the JSON array order alone). Each step
  is either `automated` (a real Go entry point — currently
  `capture-and-pin-signing-key` via `keypinning.CaptureFromKMS` and
  `execute-genesis` via `bootstrap.ExecuteGenesis`) or points at a
  `manual_steps` entry.
- **`manual_steps`**: every genuinely external step, each with an explicit
  `why_not_automated` reason — either "no executable GCP IaC framework
  exists" (S4's finding) or a named, already-reviewed structural boundary
  this repository will not silently expand (e.g. `gcswitness`'s ADR-043
  boundary forbidding Bucket Lock retention mutation from this codebase).

## Relationship to `internal/authority/bootstrap`

This package is the *plan*; `internal/authority/bootstrap` is the *one
automatable step* the plan depends on (`execute-genesis`). Nothing in this
package imports `bootstrap`, and nothing in `bootstrap` imports this
package — they are independently loadable and testable, connected only by
the `execute-genesis`/`capture-and-pin-signing-key` step IDs and the shared
`iam/manifest.json` principal IDs both reference by name.

## Real-cloud qualification gap

Every `resource_requirements` entry and every `manual_steps` entry
describes what a real environment needs; none of it has been exercised
against real GCP resources by this task. See the S6 final report's
`REAL_*_QUALIFICATION_REQUIRED` fields for exactly what remains to be
proven with real, disposable cloud resources before any of this contract
can be executed for genuine production genesis.
