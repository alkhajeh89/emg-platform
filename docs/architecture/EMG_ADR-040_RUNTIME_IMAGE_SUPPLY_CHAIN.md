# EMG ADR-040 — Runtime Image Supply Chain

**Status:** Accepted
**Owner:** EMG Founder
**Architect:** EMG Founder
**Decision Authority:** Project Architect
**Decision Date:** 2026-08-09
**Baseline:** `develop` at `c33197f4e9199e03290609f8423f4e8b036014ed`.
**Resolves:** RC001-H08 / RC-1G architecture decisions for runtime-image publication,
signing, trust identity, promotion, provenance, release evidence, and rollback evidence.
**Related:** Product Architecture Freeze §8 and §16; ADR-017 (environment portability and
air-gapped operation); ADR-034 (least-privilege service trust); `docker/dependencies.yaml`;
`.github/workflows/ci.yml`; `infra/environments/production/`.

> **This ADR authorizes architecture only.** It selects the runtime-image supply-chain
> contract needed to implement RC-1G. It does not implement or modify workflows, publish an
> image, create credentials, change a production manifest, deploy a release, or authorize an
> application/runtime behavior change.

---

## 1. Context

EMG has production Dockerfiles for five governed services and a mandatory Trivy container
scan. Version tags also produce a source archive, a repository-level CycloneDX SBOM, and
GitHub build-provenance attestations for those files. These controls do not publish or sign
the runtime images that Kubernetes deploys and do not bind a deployed image digest to its
source commit or approved workflow.

The Kubernetes production templates therefore use deliberately non-deployable
`registry.invalid/emg/...@sha256:...` references. The zero-like digests are synthetic
validation fixtures, not published artifacts. Existing release, CD, artifact-management,
and rollback documents contain no accepted registry, signing identity, promotion, or
runtime-image retention decision.

RC-1G cannot be implemented safely without selecting those mechanisms. In particular,
choosing a registry or signer only inside a workflow would create architecture in an L4
implementation artifact, contrary to GR-001.

## 2. Decision

EMG adopts a build-once, scan-before-publication runtime-image supply chain using GitHub
Container Registry (GHCR), Sigstore Cosign keyless signing with GitHub Actions OIDC, GitHub
Artifact Attestations for build provenance, immutable digest deployment identity, generated
release manifests, and generated production deployment bundles.

The governed path is:

```text
approved source commit
  -> canonical production Dockerfile
  -> build once
  -> mandatory Trivy gate
  -> GHCR publication
  -> immutable OCI digest
  -> keyless Cosign signature
  -> runtime provenance + SBOM
  -> complete release image manifest
  -> generated resolved deployment bundle
  -> retained rollback digest set
```

No later stage may proceed when an earlier mandatory stage fails.

## 3. Canonical Registry and Naming

GHCR is the canonical distribution registry for EMG v1 runtime images. Images are published
only under the GitHub repository owner's controlled namespace using this form:

```text
ghcr.io/<repository-owner>/emg-platform/<service>
```

The owner segment is derived from the trusted repository context and normalized as required
by GHCR; it is not accepted from an untrusted workflow input. Repository ownership and GHCR
package administration must remain under the same accountable organization or owner.

The authoritative deployment identity is:

```text
ghcr.io/<repository-owner>/emg-platform/<service>@sha256:<digest>
```

Mutable tags, including semantic-version and convenience tags, may be published for human
discovery. They are never authoritative deployment, promotion, signature, provenance, or
rollback identities.

## 4. Canonical Production Image Set

The governed application image set is:

- `identity`
- `audit`
- `audit-projector`
- `knowledge-graph`
- `studio-bff`

Release tooling must derive this set from the canonical production-service governance in
`docker/dependencies.yaml`: entries of type `service` with a declared production Dockerfile.
It must not maintain an independent workflow-only service list. A governed service added or
removed from that inventory must cause release validation to require the corresponding
change in image coverage. Unknown images in the generated application-image manifest are
rejected.

The Knowledge Graph migration Job reuses the `knowledge-graph` runtime image and therefore
does not create a sixth application image.

## 5. Build-Once and Security Gate

Each canonical image is built exactly once from the commit identified by the approved
versioned release. The build uses its registered production Dockerfile, repository lock
files, digest-pinned base image, and the release commit as the only source tree. Development
dependencies and mutable source branches are not injected into a release image.

The build output must be preserved as an OCI-addressable artifact so that the exact content
scanned is the content later published. Promotion between stages or environments moves the
same immutable digest; it never rebuilds application images.

The existing Trivy policy is mandatory and remains unchanged: all canonical images are
scanned, `CRITICAL` findings under the governed policy fail the gate, and publication,
signing, attestation, release-manifest finalization, and promotion depend on successful
completion of that gate. A scan of different content, a tag-only scan, or a post-publication
scan does not satisfy this decision.

## 6. Publication and Digest Capture

Only the trusted runtime-image release workflow may authenticate to GHCR for publication.
It publishes the already-scanned build output and captures the registry-confirmed immutable
digest for every canonical service. Failure to obtain or verify a canonical `sha256` digest
fails the release.

No registry credential, personal access token, or package secret is committed. Publication
uses the repository-scoped GitHub workflow token with `packages: write` only in the
publication job. Scan, test, pull-request, and ordinary branch jobs receive no package-write
or signing authority.

## 7. Signing and Trust Identity

Every published image is signed by immutable digest using Sigstore Cosign keyless signing.
The signer uses GitHub Actions OIDC; EMG stores no private image-signing key in the
repository or workflow secrets.

Verification must bind the signing certificate and transparency evidence to all of:

- the trusted GitHub Actions OIDC issuer, `https://token.actions.githubusercontent.com`;
- the EMG GitHub repository;
- the exact approved runtime-image release workflow identity;
- the approved `refs/tags/v*` release ref and event context; and
- where emitted by GitHub, the protected release environment identity.

Trust is not granted to an arbitrary workflow in the repository, a reusable workflow called
from an untrusted repository, a pull-request execution, an arbitrary branch, or a signature
whose certificate merely names the repository. Verification policy must check the complete
approved identity profile. Signing failure or verification failure fails the release.

## 8. Trusted Release Boundary and Least Privilege

Production runtime publication and signing run only for an approved version tag matching
`v*`. The tag must pass repository release protections, and the privileged release job must
use a protected GitHub environment named `production-release` with required reviewer
approval. Configuring protected tags/rulesets and that environment is an operational
prerequisite; the repository workflow must fail closed when the environment is unavailable.

Pull requests and branch pushes may build and scan but never receive `packages: write`,
`id-token: write`, `attestations: write`, release-environment secrets, or release approval.
The privileged job receives only the permissions required for its stage:

- `contents: read` to read the approved commit;
- `packages: write` to publish the scanned image;
- `id-token: write` for keyless signing and attestation; and
- `attestations: write` for GitHub provenance.

All other permissions remain absent. Action references remain commit-SHA pinned under the
existing repository policy. Repository/ref/image names come from trusted GitHub context or
validated canonical inventory, never unquoted user-controlled command fragments.

## 9. Runtime Provenance and SBOM

Each published digest must have release evidence that binds:

- source repository and exact commit SHA;
- approved workflow file and workflow run identity;
- canonical image repository and immutable OCI digest;
- the service's CycloneDX SBOM; and
- build provenance generated by the approved workflow.

GitHub Artifact Attestations, already used for source release evidence, remain the canonical
build-provenance mechanism and must attest the runtime image subject by digest. Cosign is the
canonical digest-signing mechanism; it does not introduce a competing provenance format.
The per-image SBOM is retained as release evidence and associated with that same digest.

The release must support automated verification that a digest was produced from the stated
commit by the approved workflow and that its signature satisfies §7.

## 10. Release Image Manifest

The release workflow generates one machine-readable manifest for the complete release. For
each canonical service it records at least:

- service name;
- canonical GHCR repository;
- immutable `sha256` digest and complete deployable image reference;
- source repository and commit SHA;
- workflow/run identity;
- SBOM reference and checksum; and
- signature and provenance verification references where applicable.

The manifest is generated from trusted workflow output, not manually edited. It must contain
exactly one entry for every canonical service, no undeclared application service, no mutable
tag as deployment identity, and no unresolved or synthetic digest. The complete manifest is
the release and rollback unit; a partial service set is invalid.

## 11. Promotion and Production Templates

Checked-in Kubernetes production manifests remain source templates. Release tooling produces
a separate resolved deployment bundle by replacing every governed application-image fixture
with its real, signed GHCR digest from the release image manifest. Ephemeral release digests
are not committed back to source templates.

A finalized bundle is valid only when:

- every canonical service reference matches the complete release manifest;
- every reference uses an immutable digest;
- signature and provenance verification succeeded; and
- no `registry.invalid`, zero/synthetic digest, mutable-only reference, or undeclared image
  remains.

Promotion deploys or distributes the generated bundle and the same digest set to later
environments. This ADR defines the artifact and integrity boundary; it does not automate a
production deployment.

## 12. Rollback and Retention

Every approved release retains its complete service-to-digest manifest, resolved deployment
bundle, per-image SBOMs, provenance evidence, and verification metadata. Rollback means
selecting a previously approved complete manifest and redeploying that immutable set. A
mixture of ad hoc digests from different releases is not a governed rollback.

Automated production rollback is outside this ADR. The evidence must be retained as
versioned release evidence and must not depend solely on a short-lived workflow workspace.
The legal/compliance retention duration is not approved in current governance and remains a
mandatory operational prerequisite. No duration is invented here; release evidence must not
be deleted until that policy is approved and applied.

## 13. Keycloak Provisioner Resolution

`infra/kubernetes/base/keycloak-provision.yaml` references
`registry.invalid/emg/keycloak-provisioner` with a synthetic digest. Repository evidence is
insufficient to classify it as either an EMG-built image or an approved third-party image:
there is no registered service/tool image, Dockerfile, external dependency declaration, or
documented upstream image.

It is therefore not silently added to the five-image application set and is not accepted as
a production dependency in its current form. RC-1G implementation must resolve it in exactly
one governed way:

1. If EMG-built, add a production Dockerfile and canonical image registration, then apply
   the same build, scan, publication, signing, provenance, manifest, and digest controls; or
2. If third-party, replace it with an explicitly approved upstream image pinned by immutable
   digest and govern it through the external deployment-dependency inventory and verification
   policy.

Final release validation must fail while the synthetic reference remains or while neither
ownership model is established. Selecting between these models is an implementation
prerequisite requiring evidence of the intended provisioning tool; this ADR does not guess.

## 14. Portability and Air-Gapped Deployment

GHCR is the canonical connected distribution registry for EMG v1 release artifacts, not an
application runtime dependency. After an image has been pulled, no application process calls
GitHub or GHCR APIs.

The Product Architecture Freeze requires the same container images for cloud, on-premises,
and air-gapped deployments. A release may therefore be mirrored to an approved on-premises
registry or packaged as an offline OCI bundle, but the image content must not be rebuilt.
The bundle or mirror process must preserve the governed digest set and include the SBOM,
provenance, signature, certificate/transparency verification material, and release manifest
needed for disconnected verification. Registry relocation must not change application
architecture or source content.

A future canonical-registry migration may be approved by a later ADR without changing
application services or the build-once/digest contract.

## 15. Security Properties

This decision provides:

- **PR isolation:** untrusted contributions cannot publish, sign, attest, or enter the
  protected release environment.
- **Least privilege:** package, OIDC, and attestation permissions exist only in the approved
  release job.
- **OIDC trust restriction:** verification binds issuer, repository, workflow, release ref,
  and protected boundary rather than trusting all repository workflows.
- **Digest integrity:** signatures, provenance, deployment, and rollback refer to immutable
  content rather than mutable tags.
- **Build integrity:** scan, publication, and provenance apply to the same build-once output.
- **Release integrity:** finalization requires a complete canonical image set and rejects
  placeholders or partial mappings.
- **Rollback integrity:** rollback selects a retained, previously approved complete digest
  set rather than rebuilding or manually composing images.

## 16. Alternatives Rejected

- **Unsigned runtime images.** Rejected because registry possession alone does not establish
  approved workflow origin or prevent unauthorized replacement.
- **Mutable-tag-only production identity.** Rejected because tags can move and cannot provide
  reproducible deployment or rollback identity.
- **Manually edited production digests.** Rejected because manual substitution is incomplete,
  error-prone, and cannot prove provenance or canonical-set coverage.
- **Rebuilding per environment.** Rejected because different bytes would be promoted under
  the same source release and invalidate scan, provenance, and rollback equivalence.
- **Repository-stored signing keys.** Rejected because long-lived private material expands
  secret custody and compromise risk when GitHub OIDC keyless identity is available.
- **ECR, ACR, or GAR before a deployment-provider decision.** Rejected because those choices
  would unnecessarily bind release distribution to one cloud. GHCR is tied to the governed
  source/release identity while application runtime and deployment remain provider-neutral.
- **A separate runtime provenance format.** Rejected because GitHub Artifact Attestations are
  already the repository's provenance mechanism and can bind the OCI digest subject.

## 17. Consequences

### Positive

- Every production runtime digest can be traced to an approved source commit and workflow.
- Publication, signing, provenance, promotion, and rollback operate on one immutable build.
- Production templates remain stable while releases produce deployable resolved artifacts.
- The model remains deployable to cloud, on-premises, and disconnected environments.

### Costs and constraints

- Connected release publication depends on GHCR, GitHub Actions OIDC, Sigstore availability,
  and protected GitHub repository/environment configuration.
- Offline release packaging must retain verification material and prove digest preservation.
- Release tooling must reconcile the canonical service inventory with production workload
  references and fail closed on drift.
- The Keycloak provisioner and release-evidence retention period require operational
  resolution before a production release is valid.

## 18. Non-Goals

This ADR does not implement a workflow, publish an image, create a GitHub environment,
provision credentials, deploy to Kubernetes, automate production rollback, choose a cloud
deployment provider, select a legal retention duration, change a Dockerfile, change an
application API, or alter runtime, authentication, authorization, persistence, backup, or
audit behavior.

## 19. Acceptance Criteria

- RC-1G implementation derives the five application images from canonical service governance.
- Every released image is built once, passes the existing Trivy gate, is published to the
  governed GHCR path, and is signed and attested by immutable digest.
- Verification binds the signature to the approved repository, workflow, issuer, release
  ref, and protected boundary.
- A generated complete release manifest and resolved bundle contain no placeholders.
- A retained prior complete manifest is sufficient to identify rollback images.
- Pull requests and arbitrary branches have no publication or signing authority.
- Keycloak provisioner ownership is resolved before release finalization.
- Air-gapped packaging preserves the same image content and includes offline verification
  evidence.

## Ratification

This ADR was checked against the accepted architecture and frozen product deployment models.
It adds a concrete v1 supply-chain implementation architecture without changing application
or deployment-model semantics.

**Review Outcome: Accepted.** Implementation of RC-1G is authorized subject to the explicit
operational prerequisites and fail-closed Keycloak provisioner resolution in this ADR.
