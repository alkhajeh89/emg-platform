# Wave 2 Track E — Real Kubernetes + TLS Deployment Qualification

**Date:** 2026-08-23 – 2026-08-24
**Authoritative start commit:** `a737db299e3c55299e209d9f6c758c4897d422f0`
**Scope:** prove the landed S5/S6 Kubernetes topology and the TLS fix (`82df3c8`) work end-to-end on the real GKE `emg-staging` cluster, without modifying existing EMG staging workloads.
**Explicitly out of scope, not started:** Track F end-to-end genesis, S7, production deployment, production approval.
**Does not prove:** ADR-045 production administrative independence — see `LIMITATIONS.md`.

## Cluster/cloud inventory used

| Resource | Identity | Notes |
|---|---|---|
| Cluster | `emg-staging` (`emg-platform-staging`, `me-central1-a`), `v1.35.6-gke.1641000`, `RUNNING` | Reused, read-only inventoried first (Phase 1); no existing workload touched |
| Datapath | GKE Dataplane V2 (`ADVANCED_DATAPATH`, Cilium-based) | NetworkPolicy enforcement confirmed real and active (see `DNS_NETWORKPOLICY_DEFECT.md`) |
| Qualification namespace | `ra-k8s-qual` (new, dedicated) | Never the live `emg-staging` namespace |
| Authority-side project | `emg-platform-staging` (existing) | Only new, dedicated resources created in it (GSAs, Artifact Registry repo, Secret Manager secrets) |
| Signer-side project | `emg-ra-signer-k8squal-a970703a` (new, disposable) | Fresh project; Track C/D's disposable projects never resurrected |
| Container registry | `me-central1-docker.pkg.dev/emg-platform-staging/ra-k8s-qual` (new Artifact Registry repo) | Real images built from the real, unmodified `services/recovery-authority/Dockerfile` and `recovery-signer.Dockerfile`; no image had ever been published anywhere before this qualification (`registry.invalid` in the base manifests is a real, never-resolved placeholder — confirmed via GHCR package listing returning empty) |
| `recovery-authority` image | `...recovery-authority@sha256:e7133f6646231ce9c7d47a219f22d8a28c4e64c5db95b487eac6a4e58d7ee630` | `linux/amd64`, built from real source at `a737db2` + local fsGroup/DNS fixes |
| `recovery-signer` image | `...recovery-signer@sha256:d8165ab9d8c55c3f2c1adab474ab9f0c8f5befd3eb0139dc25428cda5abbd0aa` | `linux/amd64` |
| Authority KSA/GSA | `ra-authority-k8squal` (ns `ra-k8s-qual`) → `ra-authority-k8squal@emg-platform-staging.iam.gserviceaccount.com` | Zero KMS/Spanner/GCS grants — capability absent by construction |
| Signer KSA/GSA | `ra-signer-k8squal` (ns `ra-k8s-qual`) → `ra-signer-k8squal@emg-ra-signer-k8squal-a970703a.iam.gserviceaccount.com` | `roles/cloudkms.signer` on the Track E key only |
| ESO fetch KSA/GSA | `ra-eso-k8squal` (ns `ra-k8s-qual`) → `ra-eso-k8squal@emg-platform-staging.iam.gserviceaccount.com` | `roles/secretmanager.secretAccessor` on exactly 3 qualification secrets only |
| Track E KMS key | `.../emg-ra-signer-k8squal-a970703a/.../keyRings/ra-tracke-ring/cryptoKeys/ra-tracke-key/cryptoKeyVersions/1` | `EC_SIGN_P256_SHA256`, `SOFTWARE`, fresh, Track-E-only |
| Qualification CA/cert | Self-issued, qualification-only CA + leaf cert, SAN `emg-recovery-signer.ra-k8s-qual.svc.cluster.local`, 7-day validity, ECDSA P-256, fingerprint `1A:B6:B7:F0:B7:BD:E0:63:20:48:66:3D:87:BD:61:BD:0F:DB:93:C4:B6:E9:5D:1E:3F:96:6B:02:74:AD:23:14` | Issued via the real, existing ExternalSecrets-Operator + GCP Secret Manager + WIF mechanism already landed in this repository (new namespace-scoped `SecretStore`, same pattern as `emg-staging-secrets`) — never a production/staging certificate reused |

## Phase 2 topology decision

**Hybrid provider-dependency approach**, decided after reading `cmd/recovery-authority/main.go` in full:

- `compose()`'s readiness gate (`readiness.SetReady()`) fires immediately after all dependency clients construct successfully — `spannercommit.Dial` and `gcswitness.NewClient` are non-blocking ADC/gRPC client constructors, never validated against a real, existing Spanner database or GCS bucket at startup. Only `POST /v1/verify` would ever exercise real Spanner/GCS connectivity, and Track E never calls it.
- **Option B** (qualify deployment/TLS/network boundary separately from full application readiness) was used for Spanner/witness-GCS/pin-store/ledger: placeholder-but-syntactically-valid resource-name strings (mirroring the base ConfigMap's own placeholder convention exactly), local `FileStore`/`FileLedger` via `emptyDir` (matching the base manifest, not GCS-backed). This ground was already exhaustively, really qualified with real resources in Wave 1 Track A/B and Wave 2 Track C — re-qualifying it here would be redundant, and it is explicitly out of Track E's own stated scope.
- **Option A** (provision minimal fresh disposable dependencies) was used for the **signing key specifically**, mirroring Track D's already-authorized minimal pattern (fresh disposable project, one KMS key, one signer GSA with `cloudkms.signer` only) — this makes the signerrpc positive path (`ActiveKeyID`, `SignCommittedDigest`) genuinely, fully functional end-to-end, not merely "authenticated then simulated."

## Defects discovered (both real, both fixed, both reported before fixing)

This qualification found and fixed two genuine, previously-undetected defects in the landed manifests — neither was ever caught before because no prior wave (A/B/C/D) had ever deployed these manifests to a real cluster.

1. **`FSGROUP_DEFECT.md`** — `recovery-signer`'s mounted TLS Secret was unreadable by its own non-root runtime user on any real cluster (`fsGroup` was never set). Fixed in `infra/kubernetes/base/recovery-signer.yaml`.
2. **`DNS_NETWORKPOLICY_DEFECT.md`** — the landed `emg-dns-egress` NetworkPolicy pattern permitted DNS resolution via the kube-dns backend pod's raw IP but silently blocked it via the kube-dns Service ClusterIP (the address every pod's `/etc/resolv.conf` actually uses) — on this real GKE Dataplane V2 cluster. Fixed in `infra/kubernetes/base/network-policies.yaml`.

Both fixes are covered by new, verified-failing-before/passing-after regression tests in `tests/infrastructure/test_production_manifests.py`.

## Qualification results

See:
- `TLS_MATRIX.md` — real TLS handshake positive/negative matrix
- `SIGNERRPC_AUTH_MATRIX.md` — real signerrpc bearer-auth positive/negative matrix
- `NETWORKPOLICY_MATRIX.md` — real, empirical NetworkPolicy enforcement matrix
- `POD_SECURITY.md` — live pod hardening + RBAC secret-isolation verification
- `RESTART_FAILURE.md` — restart/failure behavior
- `ATTACK_MATRIX.md` — consolidated attack-matrix outcomes
- `PROVIDER_FACT_CHECK.md`
- `CLEANUP.md`
- `LIMITATIONS.md`
- `SHA256SUMS.txt`

## Summary

- Real TLS 1.3 handshake, correct CA validation, correct SAN validation: **qualified**.
- Real signerrpc bearer-auth (Google-signed ID token, audience + allow-list enforcement): **qualified**, both positive and negative.
- Real NetworkPolicy enforcement (authority↔signer allowed; every other combination denied, including cross-namespace access to the real live `emg-staging` workloads): **qualified**.
- Real Cloud KMS `AsymmetricSign` via the real signerrpc path: **qualified** (72/71-byte DER ECDSA signatures produced).
- Two real defects found, fixed, regression-tested, requalified.
- No P0/P1 remains open. No public signer exposure at any point. No static credentials anywhere. No existing `emg-staging` workload touched or modified.
