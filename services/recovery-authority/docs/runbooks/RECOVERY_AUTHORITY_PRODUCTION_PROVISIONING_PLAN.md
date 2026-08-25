# Recovery Authority — Production Infrastructure Provisioning Plan (Gate A)

**Status: PLAN ONLY — nothing in this document has been executed.** This is
the resource-by-resource plan Gate A's governance approval
(`RECOVERY_AUTHORITY_ADMINISTRATIVE_INDEPENDENCE_DECISION_PACKAGE.md`)
requires before any production GCP resource may be created. **No GCP
project, organization, Cloud Identity domain, billing account, IAM
binding, Kubernetes object, or Spanner/KMS/GCS resource has been created,
modified, or bound by this document.** Where a resource's prerequisite
(an independent administrative root) does not yet exist, that resource is
explicitly marked `BLOCKED_ON_PREREQUISITE` rather than planned as if it
did.

**Hard prerequisite check result (see the accompanying final report for
the full discovery output): only one GCP organization is currently visible
to this session's credentials (`ms-alkhaja-org`, ID `1090730370932`).
No second, independently governed Cloud Identity/Workspace root exists.**
Domain A may proceed to detailed planning on the existing organization
(same-org placement for Domain A was never prohibited by any ADR). Domain
B and Domain C's resources below are planned in full but **cannot be
safely created until their prerequisite roots exist** — creating them
under the existing organization instead would not satisfy Decision 1/3 and
is explicitly forbidden by this task's own instruction not to substitute
another project, folder, or the same Workspace.

## Provisioning order (dependency-respecting)

1. Domain A: project → Spanner instance → database/schema → witness bucket → GSAs → WIF → Bucket Lock (last, deliberately — see its own row)
2. Kubernetes: namespace → KSAs → WIF bindings → TLS secret mechanism → NetworkPolicies → ConfigMaps → image digests
3. Domain B: **[BLOCKED]** independent root → signing project → KMS key ring/key/version → signer GSA → pin-store bucket → WIF
4. Domain C: **[BLOCKED]** independent root/project → compromise-ledger bucket → ledger writer → verifier read binding
5. Bootstrap: temporary principal IAM *definition* (safe, declarative) — its actual *activation* is Gate B scope, not Gate A

---

## DOMAIN A — Authority / Witness

### A1. Production authority project
- Administrative domain: A. Organization/root: existing `ms-alkhaja-org` (1090730370932). Project: new, e.g. `emg-ra-prod-authority` (name TBD by operator, never a name this plan invents as final).
- Billing relationship: separate billing account (Decision 4 default).
- Owner/admin group: AUTHORITY_ADMIN_GROUP.
- Runtime principal: N/A at project-creation time.
- IAM roles: project-creation grant to AUTHORITY_ADMIN_GROUP only; no broad `roles/owner` standing grant to any runtime identity.
- Data classification: none yet (empty project).
- Irreversible properties: project ID is permanent once chosen; project deletion is possible but subject to any liens placed later.
- Validation command: `gcloud projects describe <project-id> --format="value(parent.id,parent.type)"` — confirm parent is the approved organization, not a stray folder.
- Rollback capability: full (`gcloud projects delete`) until Bucket Lock (A5) or KMS-equivalent irreversible state exists.
- Safe before Gate B: Yes.

### A2. Spanner instance
- Domain: A. Root/project: A1.
- Billing: inherits A1's account.
- Owner/admin group: AUTHORITY_ADMIN_GROUP.
- Runtime principal: none directly (instance-level).
- IAM: `roles/spanner.admin` restricted to AUTHORITY_ADMIN_GROUP only; runtime identity never holds this role (ADR-044 §15).
- Data classification: none until schema/data exist.
- Irreversible properties: none at instance-creation; billable resource only.
- Validation command: `gcloud spanner instances describe <instance> --format="value(config,nodeCount)"`.
- Rollback capability: full (`gcloud spanner instances delete`) at this stage.
- Safe before Gate B: Yes.

### A3. Authority database/schema
- Domain: A. Project/instance: A1/A2.
- Owner/admin group: AUTHORITY_ADMIN_GROUP (schema/DDL rights); explicitly excluded from `recovery-authority-runtime` per `iam/README.md`'s own finding that `roles/spanner.databaseUser` must not be granted wholesale.
- Runtime principal: `recovery-authority-runtime` gets the custom, DDL-excluded role only (already defined in `iam/manifest.json`).
- IAM: apply the exact custom role from `iam/manifest.json`, never `roles/spanner.databaseUser` unmodified (per that manifest's own Phase 2 finding).
- Data classification: SECURITY_CRITICAL (authority state) once populated.
- Irreversible properties: none at schema-creation; data written later is bound by Bucket Lock's witness, not the database itself.
- Validation command: apply `scripts/emulator/schema.sql`'s DDL (already-reviewed, unmodified) via `gcloud spanner databases ddl update`; then `gcloud spanner databases ddl describe` to confirm exact column/table match.
- Rollback capability: full until first real genesis write.
- Safe before Gate B: Yes (schema only — no data written yet).

### A4. Witness GCS bucket
- Domain: A. Project: A1.
- Owner/admin group: AUTHORITY_ADMIN_GROUP for bucket administration; `recovery-authority-runtime` gets only `CreateExactIfAbsent`-equivalent narrow permissions (no `storage.objects.delete`, no `storage.buckets.update` on retention).
- IAM: exact custom role from `iam/manifest.json`; explicitly exclude `storage.buckets.setRetentionPolicy` from the runtime principal (retention locking is a rare, governance-controlled, one-time action — ADR-044 §15).
- Data classification: SECURITY_CRITICAL (immutable COMMITTED witness records).
- Irreversible properties: bucket itself is reversible (deletable) **until** A5 locks retention.
- Validation command: `gsutil retention get gs://<bucket>` (should report `Not currently set` until A5).
- Rollback capability: full until A5.
- Safe before Gate B: Yes (bucket creation, unlocked).

### A5. Bucket Lock retention configuration
- Domain: A. Resource: A4's bucket.
- Owner/admin group: AUTHORITY_ADMIN_GROUP, and only via the explicit Decision 7 approval-and-evidence process — never a default applied automatically alongside A4.
- Irreversible properties: **genuinely irreversible** — locking a retention policy can never be undone or shortened (ADR-044 §11, empirically reconfirmed by S7's own real lien encounter).
- Validation command: `gsutil retention get gs://<bucket>` before locking (confirm intended duration); `gsutil retention lock gs://<bucket>` only after Decision-7 sign-off is recorded; `gcloud storage buckets describe --format="value(retentionPolicy.isLocked)"` after, to confirm.
- Rollback capability: **none, by design**, once locked.
- Safe before Gate B: **No — this specific action should be deferred as close as practical to the actual genesis event**, even though the bucket itself (A4) is created earlier; locking is the one Domain A action this plan recommends sequencing right before Gate B's genesis, not as part of routine Gate A infrastructure setup, to minimize the irreversible window.

### A6. GSAs (`recovery-authority-runtime`, `recovery-verification-read`, `recovery-bootstrap-deployment`)
- Domain: A. Project: A1.
- Owner/admin group: AUTHORITY_ADMIN_GROUP creates; principal identities themselves hold only their own already-defined `iam/manifest.json` permission sets.
- IAM: exact bindings from `iam/manifest.json` — no ad hoc broadening.
- Irreversible properties: none (GSAs are deletable/recreatable).
- Validation command: `gcloud iam service-accounts describe <email>`; cross-check granted roles against `manifest.json` via the existing `iam` package's own tests run against the real exported policy (`gcloud projects get-iam-policy <project> --format=json`, diffed against `manifest.json`'s `required_permissions`/`forbidden_permissions`).
- Rollback capability: full.
- Safe before Gate B: Yes.

### A7. WIF (Domain A)
- Domain: A. Project: A1.
- Owner/admin group: AUTHORITY_ADMIN_GROUP.
- Runtime principal: binds `recovery-authority`'s Kubernetes service account to `recovery-authority-runtime`'s GSA.
- IAM: workload identity pool + provider scoped to the specific KSA namespace/name only, never a wildcard binding.
- Irreversible properties: none.
- Validation command: `gcloud iam workload-identity-pools providers describe`; confirm `attribute-condition` narrows to the exact KSA.
- Rollback capability: full.
- Safe before Gate B: Yes.

---

## DOMAIN B — Signing — **BLOCKED_ON_PREREQUISITE**

**None of the following may be created until Decision 1's independent Cloud Identity/Workspace root exists and is independently verified as genuinely separate (Phase 3).** Planned in full below so the plan is ready the moment that prerequisite is resolved — not as authorization to create any of it now.

### B0. Independent administrative root (prerequisite)
- Status: **DOES NOT EXIST** (Phase 3 finding).
- What must happen, and by whom: see the Final Report's "Exact human/business action required" — this is not a `gcloud` operation.

### B1. Signing project
- Domain: B. Organization/root: the new, independent Cloud Identity/Workspace root once it exists. Billing: separate account (Decision 4).
- Owner/admin group: SIGNING_ADMIN_GROUP — must have zero membership overlap with AUTHORITY_ADMIN_GROUP.
- Safe before Gate B: N/A — blocked.

### B2. KMS key ring / key / version
- Domain: B. Project: B1.
- Owner/admin group: SIGNING_ADMIN_GROUP holds key-administration; `recovery-signer`'s GSA holds `cloudkms.cryptoKeyVersions.useToSign` only (never `viewPublicKey`/admin, per `kmssigner`'s own boundary test).
- Data classification: SECURITY_CRITICAL (private key material, provider-held).
- Irreversible properties: key version destruction is irreversible (ADR-045 §6); disablement is reversible but stops live `GetPublicKey`.
- Validation command: `gcloud kms keys versions describe --format="value(state)"`.
- Rollback capability: reversible (disable) until destroy; ring/key deletion follows GCP's own 24h+ scheduled-destruction window.
- Safe before Gate B: N/A — blocked.

### B3. Signer GSA
- Domain: B. Project: B1. Owner: SIGNING_ADMIN_GROUP. Runtime principal: `recovery-signer`.
- IAM: `cloudkms.cryptoKeyVersions.useToSign` only, on the exact key version.
- Safe before Gate B: N/A — blocked.

### B4. Pin-store bucket
- Domain: B (per `keypinning.GCSStore`'s own doc comment — administered by the signing domain, never authority/witness).
- Data classification: SECURITY_CRITICAL (pinned historical public keys).
- Irreversible properties: none at creation; retention policy for this bucket is a separate Decision-7-governed choice if applied.
- Safe before Gate B: N/A — blocked.

### B5. WIF (Domain B)
- Binds `recovery-signer`'s KSA to its GSA, scoped narrowly, mirroring A7.
- Safe before Gate B: N/A — blocked.

---

## DOMAIN C — Compromise Ledger — **BLOCKED_ON_PREREQUISITE**

### C0. Independent domain/project (prerequisite)
- Status: **DOES NOT EXIST** (Phase 3 finding) — per Decision 3, this must be a third domain, independent of both A and B.

### C1. Compromise-ledger bucket
- Domain: C. Data classification: SECURITY_CRITICAL (governance/distrust records).
- Irreversible properties: append-only by design (`compromiseledger.Ledger` interface has no mutation method, S3-qualified); the bucket itself is reversible until any retention lock is separately applied.
- Safe before Gate B: N/A — blocked.

### C2. Ledger writer principal
- Domain: C. Owner: LEDGER_ADMIN_GROUP. Distinct from SIGNING_ADMIN_GROUP (ADR-045 §7 property 2).
- Safe before Gate B: N/A — blocked.

### C3. Verifier read binding
- Domain: A's runtime (`recovery-authority-runtime`/`kmsverifier`) gets read-only access into C1 — the one permitted cross-domain data-plane flow into Domain C.
- Safe before Gate B: N/A — blocked (depends on C1 existing).

---

## KUBERNETES

### K1. Production namespace
- Domain: cross-cutting (hosts both Domain A and Domain B runtime workloads, in their respective clusters/projects — not evidence against domain separation, since namespace-level Kubernetes isolation is orthogonal to GCP IAM/organization separation).
- Validation command: `kubectl get ns <namespace> -o yaml`.
- Rollback capability: full.
- Safe before Gate B: Yes (for Domain A's namespace); Domain B's namespace is blocked with B0.

### K2. `recovery-authority` KSA
- Bound to A6/A7. Safe before Gate B: Yes.

### K3. `recovery-signer` KSA
- Bound to B3/B5. Safe before Gate B: N/A — blocked with Domain B.

### K4. TLS secret mechanism
- Domain: A (server-side, `recovery-signer`) and A (client-trust, `recovery-authority`'s CA file config) — per `cmd/recovery-authority`'s own documented one-way-TLS trust model; no mTLS.
- Irreversible properties: none (certificates are rotatable).
- Safe before Gate B: `recovery-authority`'s trust configuration is Gate-A-safe; `recovery-signer`'s own serving certificate is blocked with Domain B.

### K5. NetworkPolicies
- Restrict `recovery-authority`'s namespace to only the egress needed (Spanner, GCS, the signer endpoint) — already-qualified pattern from Track E.
- Safe before Gate B: Yes for Domain A's policies; Domain B's are blocked.

### K6. ConfigMaps
- Non-secret configuration (database name, bucket name, endpoints). Safe before Gate B: Yes for Domain A values; Domain B values blocked.

### K7. Image digests
- Pin `cmd/recovery-authority`, `cmd/recovery-signer`, `cmd/recovery-rotate` container images by digest, never a mutable tag, in the deployment manifests — already-established repository convention.
- Safe before Gate B: Building/pinning the `recovery-authority`/`recovery-rotate` images is Gate-A-safe; `recovery-signer`'s image can be built but its deployment is blocked with Domain B.

---

## BOOTSTRAP

### BS1. Temporary bootstrap principal (`recovery-bootstrap-deployment`) — IAM definition
- Domain: A. Already declared, unbound, in `iam/manifest.json` and cross-referenced in `provisioning/contract.json`.
- Irreversible properties: none — the IAM role definition itself grants nothing until bound.
- Safe before Gate B: Yes (declaring/creating the role definition, not activating a standing grant).

### BS2. Bootstrap principal activation + dual-control approval model
- This is the one-time, temporary binding exercised **at** the actual genesis event, then immediately revoked (already real-cloud-qualified by Track F's bootstrap-revocation evidence).
- Safe before Gate B: **No** — by definition this occurs at genesis time, which is Gate B's own scope, not Gate A infrastructure provisioning.

---

## Summary: what Gate A approval actually permits creating today

Given the Phase 3 finding, **Gate A approval currently permits proceeding only with Domain A (A1–A4, A6–A7) and the Domain-A-scoped half of Kubernetes/Bootstrap (K1–K2, K4–K7 partial, BS1)** — not A5 (defer to just-before-genesis per its own row), and not any Domain B or Domain C resource, which remain `BLOCKED_ON_PREREQUISITE` until their independent administrative roots exist.
